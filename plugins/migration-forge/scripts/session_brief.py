#!/usr/bin/env python3
"""SessionStart hook: when the session opens inside a migration workspace, print a 5-line brief
(stdout becomes context). Silent everywhere else."""
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forgelib import FORGE_DIR, find_workspace, read_json  # noqa: E402

try:
    ev = json.load(sys.stdin)
except json.JSONDecodeError:
    ev = {}
ws = find_workspace(ev.get("cwd") or os.getcwd())
if not ws:
    sys.exit(0)
st = read_json(ws / FORGE_DIR / "state.json", {}) or {}
card = read_json(ws / FORGE_DIR / "gates" / "latest.json") or {}
tr = read_json(ws / FORGE_DIR / "tracker" / "tracker.json") or {"items": {}}
counts = {}
for t in tr["items"].values():
    counts[t["status"]] = counts.get(t["status"], 0) + 1
print(f"[migration-forge] run '{st.get('name')}' phase={st.get('phase')} target={st.get('target')}")
print(f"  approvals: {', '.join(st.get('approvals', {})) or 'none'}; Jenkins verdicts imported: {st.get('iteration', 0)}"
      + (f"; latest {card.get('verdict')} for {str(card.get('head') or '?')[:10]}" if card else ""))
print(f"  tickets: {json.dumps(counts)}")
print("  Resume with /migration-forge:status (or /migration-forge:migrate to continue the pipeline).")
