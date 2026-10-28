#!/usr/bin/env python3
"""Cost evidence for the cost gate.

1. Claude token spend for this run: sums usage from Claude Code transcripts of this workspace
   (~/.claude/projects/<encoded-workspace>/**/*.jsonl) since state.started_at, deduped by message id.
   tokens_total = input + output + cache_creation (cache reads reported separately; they are cheap).
2. Infra cost: Infracost on IaC (*.tf) in legacy and modernized trees, if infracost is installed
   and authenticated. Increase % is computed only when both sides have a figure.
3. Headless runs (`claude -p --output-format json`, e.g. a Jenkins loop): exact USD per call in the ledger
   forge/cost/ledger.jsonl, gated by checks.cost.max_usd / max_calls / max_usd_per_call.

  cost_estimate.py [--root modernized/<name>] [--out forge/cost.json]
  claude -p ... --output-format json | cost_estimate.py record-claude [--label modernize]
  cost_estimate.py check          # exit 42 = stop calling Claude (budget or call cap reached, or a call's cost unknown)
  cost_estimate.py remaining      # USD to pass to `claude --max-budget-usd`
Optional USD for tokens: set "cost": {"usd_per_mtok": {"input":..,"output":..,"cache_creation":..,"cache_read":..}}
in forge/gates.json (prices change; none are hardcoded).
"""
import argparse
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

from forgelib import forge, load_gates, now, read_json, state, workspace, write_json


def ledger_path(ws):
    return forge(ws) / "cost" / "ledger.jsonl"


def ledger(ws):
    """Totals over the ledger, or None when no call was recorded. Calls whose cost could not be read count as
    `unparsed`: their spend is unknown, so the cost check fails instead of treating it as $0."""
    p = ledger_path(ws)
    if not p.exists():
        return None
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    known = [r["usd"] for r in rows if isinstance(r.get("usd"), (int, float))]
    return {"usd_total": round(sum(known), 4), "calls": len(rows), "max_usd_per_call": round(max(known, default=0), 4),
            "unparsed": len(rows) - len(known),
            "tokens": sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in rows)}


def record_claude(ws, label):
    raw = sys.stdin.read()
    row = {"at": now(), "label": label}
    try:
        d = json.loads(raw)
        if isinstance(d, list):
            d = next((x for x in reversed(d) if isinstance(x, dict) and x.get("type") == "result"), {})
        u = d.get("usage", {}) or {}
        row.update(usd=float(d["total_cost_usd"]), session=d.get("session_id"), turns=d.get("num_turns"),
                   input_tokens=(u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                                 + u.get("cache_read_input_tokens", 0)),
                   output_tokens=u.get("output_tokens", 0))
    except (ValueError, KeyError, TypeError, AttributeError):
        row.update(usd=None, error="could not read total_cost_usd from claude output", output_tail=raw[-300:])
    p = ledger_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row) + "\n")
    print(f"recorded {label}: " + (f"${row['usd']:.4f}" if row["usd"] is not None else "UNKNOWN cost (counted as unparsed)"))
    sys.exit(0 if row["usd"] is not None else 1)


def budget_cmd(ws, cmd):
    t = (load_gates(ws)["checks"].get("cost") or {})
    lim = {k: t.get(k) or 0 for k in ("max_usd", "max_calls", "max_usd_per_call")}
    tot = ledger(ws) or {"usd_total": 0, "calls": 0, "unparsed": 0}
    if cmd == "check":
        why = ([f"spent ${tot['usd_total']} >= ${lim['max_usd']}"] if lim["max_usd"] and tot["usd_total"] >= lim["max_usd"] else []) \
            + ([f"{tot['calls']} calls >= {lim['max_calls']}"] if lim["max_calls"] and tot["calls"] >= lim["max_calls"] else []) \
            + ([f"{tot['unparsed']} call(s) with unknown cost"] if tot["unparsed"] else [])
        print(f"spent ${tot['usd_total']} in {tot['calls']} call(s) -> " + ("STOP: " + "; ".join(why) if why else "ok"))
        sys.exit(42 if why else 0)
    if not lim["max_usd"] and not lim["max_usd_per_call"]:
        sys.exit("no budget set: put checks.cost.max_usd (and max_usd_per_call) in forge/gates.json")
    caps = ([lim["max_usd"] - tot["usd_total"]] if lim["max_usd"] else []) + ([lim["max_usd_per_call"]] if lim["max_usd_per_call"] else [])
    print(f"{max(0.0, min(caps)):.2f}")


def _projects_dir():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(pathlib.Path.home() / ".claude")
    return pathlib.Path(base) / "projects"


def token_spend(ws, since):
    enc = re.sub(r"[^A-Za-z0-9]", "-", str(ws))
    d = _projects_dir() / enc
    seen, tot = set(), {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    files = glob.glob(str(d / "**" / "*.jsonl"), recursive=True) if d.is_dir() else []
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = e.get("message") or {}
                u = msg.get("usage")
                if not u or (since and (e.get("timestamp") or "") < since):
                    continue
                key = msg.get("id") or e.get("uuid")
                if key in seen:
                    continue
                seen.add(key)
                tot["input"] += u.get("input_tokens", 0) or 0
                tot["output"] += u.get("output_tokens", 0) or 0
                tot["cache_creation"] += u.get("cache_creation_input_tokens", 0) or 0
                tot["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
    return tot, len(files), str(d)


def infracost(path, out):
    if not shutil.which("infracost") or not glob.glob(str(pathlib.Path(path) / "**" / "*.tf"), recursive=True):
        return None
    p = subprocess.run(f'infracost breakdown --path "{path}" --format json --out-file "{out}"',
                       shell=True, capture_output=True, text=True)
    d = read_json(out) if p.returncode == 0 else None
    try:
        return float(d["totalMonthlyCost"]) if d else None
    except (KeyError, TypeError, ValueError):
        return None


def estimate(ws, st, root, out):
    g = load_gates(ws)
    tok, nfiles, tdir = token_spend(ws, st.get("started_at"))
    res = {"tokens_total": tok["input"] + tok["output"] + tok["cache_creation"],
           "tokens": tok, "transcripts_scanned": nfiles, "transcripts_dir": tdir, "ledger": ledger(ws)}
    prices = (g.get("cost") or {}).get("usd_per_mtok")
    if prices:
        res["tokens_usd"] = round(sum(tok[k] * float(prices.get(k, 0)) / 1e6 for k in tok), 2)
    outdir = pathlib.Path(out).parent
    new = infracost(root, outdir / "infracost-modernized.json") if root else None
    legacy = ws / (st.get("legacy") or "")
    old = infracost(legacy, outdir / "infracost-legacy.json") if st.get("legacy") and legacy.exists() else None
    res.update(monthly_usd=new, legacy_monthly_usd=old,
               monthly_increase_pct=round(100 * (new - old) / old, 2) if new is not None and old else None,
               infra_note=None if new is not None else "no IaC or infracost unavailable: infra cost not gated")
    write_json(out, res)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["estimate", "record-claude", "check", "remaining"], default="estimate")
    ap.add_argument("--label", default="modernize")
    ap.add_argument("--root")
    ap.add_argument("--out")
    a = ap.parse_args()
    ws, st = workspace(), state()
    if a.cmd == "record-claude":
        record_claude(ws, a.label)
    if a.cmd in ("check", "remaining"):
        budget_cmd(ws, a.cmd)
        sys.exit(0)
    root = pathlib.Path(a.root or st.get("modernized_root") or ".").resolve()
    print(json.dumps(estimate(ws, st, root, a.out or forge(ws) / "cost.json"), indent=2))
