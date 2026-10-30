#!/usr/bin/env python3
"""Cost report inputs for the pilot projection and status (cost gating itself runs in the Jenkins pipeline).

1. LLM token spend for this run, since state.started_at, from every source that exists:
   - forge/usage.jsonl: a tool-neutral ledger. Any agent, harness or human appends to it with
     `cost_estimate.py log --input N --output N [--cache-creation N] [--cache-read N] [--source <tool>]`.
   - Claude Code transcripts of this workspace (~/.claude/projects/<encoded-workspace>/**/*.jsonl), when present,
     deduped by message id. Other tools leave this source empty.
   tokens_total = input + output + cache_creation (cache reads reported separately; they are cheap).
2. Infra cost: Infracost on IaC (*.tf) in legacy and modernized trees, if infracost is installed
   and authenticated. Increase % is computed only when both sides have a figure.

  cost_estimate.py [report] [--root modernized/<name>] [--out forge/cost.json]
  cost_estimate.py log --input N --output N [--cache-creation N] [--cache-read N] [--source codex] [--note "..."]
Budget: cost.max_tokens in settings (0 = none). Optional USD for tokens: set
"cost": {"usd_per_mtok": {"input":..,"output":..,"cache_creation":..,"cache_read":..}} in forge/settings.json
(prices change; none are hardcoded).
"""
import argparse
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess

from forgelib import forge, load_settings, now, read_json, state, workspace, write_json

KEYS = ("input", "output", "cache_creation", "cache_read")


def _projects_dir():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(pathlib.Path.home() / ".claude")
    return pathlib.Path(base) / "projects"


def ledger_spend(ws, since):
    """Totals from forge/usage.jsonl and the number of entries counted."""
    tot, n = dict.fromkeys(KEYS, 0), 0
    led = forge(ws) / "usage.jsonl"
    if led.is_file():
        for line in led.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since and (e.get("at") or "") < since:
                continue
            n += 1
            for k in KEYS:
                tot[k] += int(e.get(k) or 0)
    return tot, n


def token_spend(ws, since):
    """Totals from Claude Code transcripts, the number of transcript files, and their folder."""
    enc = re.sub(r"[^A-Za-z0-9]", "-", str(ws))
    d = _projects_dir() / enc
    seen, tot = set(), dict.fromkeys(KEYS, 0)
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
    cost = load_settings(ws).get("cost") or {}
    tr, nfiles, tdir = token_spend(ws, st.get("started_at"))
    led, nled = ledger_spend(ws, st.get("started_at"))
    tok = {k: tr[k] + led[k] for k in KEYS}
    res = {"tokens_total": tok["input"] + tok["output"] + tok["cache_creation"], "max_tokens": cost.get("max_tokens") or 0,
           "tokens": tok, "sources": {"usage_ledger_entries": nled, "claude_code_transcripts": nfiles},
           "transcripts_dir": tdir}
    if not nfiles and not nled:
        res["tokens_note"] = ("no usage recorded (forge/usage.jsonl is empty and no Claude Code transcripts were found): "
                              "spend unknown, not zero. Log usage with `forge cost log`.")
    prices = cost.get("usd_per_mtok")
    if prices:
        res["tokens_usd"] = round(sum(tok[k] * float(prices.get(k, 0)) / 1e6 for k in tok), 2)
    outdir = pathlib.Path(out).parent
    new = infracost(root, outdir / "infracost-modernized.json") if root else None
    legacy = ws / (st.get("legacy") or "")
    old = infracost(legacy, outdir / "infracost-legacy.json") if st.get("legacy") and legacy.exists() else None
    res.update(monthly_usd=new, legacy_monthly_usd=old,
               monthly_increase_pct=round(100 * (new - old) / old, 2) if new is not None and old else None,
               infra_note=None if new is not None else "no IaC or infracost unavailable: infra cost is an estimate only")
    write_json(out, res)
    return res


def log_usage(ws, a):
    e = {"at": now(), "source": a.source, **{k: getattr(a, k) or 0 for k in KEYS}}
    if a.note:
        e["note"] = a.note
    with open(forge(ws) / "usage.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(e) + "\n")
    print(f"logged {sum(e[k] for k in KEYS)} tokens from {a.source}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", nargs="?", choices=["report", "log"], default="report")
    ap.add_argument("--root")
    ap.add_argument("--out")
    for k in KEYS:
        ap.add_argument("--" + k.replace("_", "-"), dest=k, type=int, default=0)
    ap.add_argument("--source", default="manual", help="the tool or harness that spent the tokens")
    ap.add_argument("--note")
    a = ap.parse_args()
    ws, st = workspace(), state()
    if a.action == "log":
        log_usage(ws, a)
        raise SystemExit(0)
    root = pathlib.Path(a.root or st.get("modernized_root") or ".").resolve()
    print(json.dumps(estimate(ws, st, root, a.out or forge(ws) / "cost.json"), indent=2))
