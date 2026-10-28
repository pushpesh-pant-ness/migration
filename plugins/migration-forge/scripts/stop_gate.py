#!/usr/bin/env python3
"""Stop hook: refuse to end the turn while the imported Jenkins verdict is FAIL and remediation budget remains.

Active only in a migration workspace during gate/remediate/verify/harden phases.
Never loops: honours stop_hook_active, the iteration cap, and a forge/PAUSE file (touch it to opt out).
Lets the turn end once a fix has been committed after the failing verdict (HEAD moved): the run then waits for
Jenkins to build the new commit.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forgelib import FORGE_DIR, find_workspace, load_settings, read_json  # noqa: E402


def head(ws):
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws, capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def main():
    try:
        ev = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)
    if ev.get("stop_hook_active"):
        sys.exit(0)
    ws = find_workspace(ev.get("cwd") or os.getcwd())
    if not ws or (ws / FORGE_DIR / "PAUSE").exists():
        sys.exit(0)
    st = read_json(ws / FORGE_DIR / "state.json", {}) or {}
    if st.get("phase") not in ("gate", "remediate", "verify", "harden"):
        sys.exit(0)
    card = read_json(ws / FORGE_DIR / "gates" / "latest.json")
    if not card or card.get("verdict") != "FAIL":
        sys.exit(0)
    if card.get("head") and head(ws) not in (None, card["head"]):
        sys.exit(0)  # a fix is committed after the failing verdict: waiting for Jenkins on the new commit
    fails_in_a_row = 0
    for h in reversed(st.get("gate_history", [])):
        if h["verdict"] != "FAIL":
            break
        fails_in_a_row += 1
    cap = load_settings(ws).get("max_remediation_iterations", 3)
    if fails_in_a_row > cap:
        sys.exit(0)  # budget exhausted: the remediate skill escalates to the human
    top = "; ".join(f"{f['check']}: {', '.join(f['reasons'])}" for f in card.get("failures", [])[:3])
    print(json.dumps({"decision": "block", "reason":
        f"The Jenkins quality gate (iteration {card.get('iteration')}) is FAIL. "
        f"Remediation attempt {fails_in_a_row}/{cap}. Top failures: {top}. "
        "Run /migration-forge:remediate now (fix, commit, let Jenkins build the commit, then import its result), "
        "or if you are blocked, run state.py phase escalated and write forge/ESCALATION.md for the user."}))
    sys.exit(0)


if __name__ == "__main__":
    main()
