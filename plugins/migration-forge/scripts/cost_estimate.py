#!/usr/bin/env python3
"""Cost evidence for the cost gate.

1. Claude token spend for this run: sums usage from Claude Code transcripts of this workspace
   (~/.claude/projects/<encoded-workspace>/**/*.jsonl) since state.started_at, deduped by message id.
   tokens_total = input + output + cache_creation (cache reads reported separately; they are cheap).
2. Infra cost: Infracost on IaC (*.tf) in legacy and modernized trees, if infracost is installed
   and authenticated. Increase % is computed only when both sides have a figure.

  cost_estimate.py [--root modernized/<name>] [--out forge/cost.json]
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

from forgelib import forge, load_gates, read_json, state, workspace, write_json


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
           "tokens": tok, "transcripts_scanned": nfiles, "transcripts_dir": tdir}
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
    ap.add_argument("--root")
    ap.add_argument("--out")
    a = ap.parse_args()
    ws, st = workspace(), state()
    root = pathlib.Path(a.root or st.get("modernized_root") or ".").resolve()
    print(json.dumps(estimate(ws, st, root, a.out or forge(ws) / "cost.json"), indent=2))
