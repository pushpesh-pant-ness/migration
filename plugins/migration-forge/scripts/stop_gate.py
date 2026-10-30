#!/usr/bin/env python3
"""Remediation obligation: don't end the turn while the imported Jenkins verdict is FAIL and remediation budget remains.

Active only in a migration workspace during gate/remediate/verify/harden phases.
Never loops: honours the iteration cap and a forge/PAUSE file (touch it to opt out).
Lets the turn end once a fix has been committed after the failing verdict (a commit that changes files outside forge/;
committing the verdict or a phase move is not a fix): the run then waits for Jenkins to build the new commit.

  - Any tool: `forge next` prints the obligation and exits 3 while it holds (agents run it before ending a turn).
  - Claude Code: hooks/hooks.json runs this file as the Stop hook (JSON event on stdin, honours stop_hook_active).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forgelib import FORGE_DIR, code_changes, find_workspace, git_head, load_settings, not_code, read_json  # noqa: E402


def fix_committed(ws, card):
    """Has code (not forge/ evidence, not the imported results folder) been committed since the commit Jenkins tested?"""
    tested, now = card["head"], git_head(ws)
    if now in (None, tested):
        return False
    changed = code_changes(ws, tested, exclude=not_code(ws, card))
    return bool(changed) if changed is not None else True  # git can't compare (history rewritten): trust the move


def obligation(ws):
    """The reason the agent must keep remediating, or None."""
    if not ws or (ws / FORGE_DIR / "PAUSE").exists():
        return None
    st = read_json(ws / FORGE_DIR / "state.json", {}) or {}
    if st.get("phase") not in ("gate", "remediate", "verify", "harden"):
        return None
    card = read_json(ws / FORGE_DIR / "gates" / "latest.json")
    if not card or card.get("verdict") != "FAIL":
        return None
    if card.get("head") and fix_committed(ws, card):
        return None  # a fix is committed after the failing verdict: waiting for Jenkins on the new commit
    fails_in_a_row = 0
    for h in reversed(st.get("gate_history", [])):
        if h["verdict"] != "FAIL":
            break
        fails_in_a_row += 1
    cap = load_settings(ws).get("max_remediation_iterations", 3)
    if fails_in_a_row > cap:
        return None  # budget exhausted: the remediate skill escalates to the human
    top = "; ".join(f"{f['check']}: {', '.join(f['reasons'])}" for f in card.get("failures", [])[:3])
    return (f"The Jenkins quality gate (iteration {card.get('iteration')}) is FAIL. "
            f"Remediation attempt {fails_in_a_row}/{cap}. Top failures: {top}. "
            "Follow the remediate skill now (fix the code, commit, let Jenkins build the commit, then import its result; "
            "committing only forge/ evidence does not count as a fix), "
            "or if you are blocked, run `forge state phase escalated` and write forge/ESCALATION.md for the user.")


def main():
    """Claude Code Stop hook adapter."""
    try:
        ev = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)
    if ev.get("stop_hook_active"):
        sys.exit(0)
    reason = obligation(find_workspace(ev.get("cwd") or os.getcwd()))
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    main()
