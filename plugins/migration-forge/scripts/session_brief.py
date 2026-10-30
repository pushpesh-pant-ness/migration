#!/usr/bin/env python3
"""Run brief: when inside a migration workspace, print a 5-line brief. Silent everywhere else.
`forge brief` in any tool; in Claude Code the SessionStart hook runs this file (stdout becomes context)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forgelib import FORGE_DIR, find_workspace, read_json  # noqa: E402


def brief(ws):
    st = read_json(ws / FORGE_DIR / "state.json", {}) or {}
    card = read_json(ws / FORGE_DIR / "gates" / "latest.json") or {}
    tr = read_json(ws / FORGE_DIR / "tracker" / "tracker.json") or {"items": {}}
    counts = {}
    for t in tr["items"].values():
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    return [f"[migration-forge] run '{st.get('name')}' phase={st.get('phase')} target={st.get('target')}",
            f"  approvals: {', '.join(st.get('approvals', {})) or 'none'}; Jenkins verdicts imported: {st.get('iteration', 0)}"
            + (f"; latest {card.get('verdict')} for {str(card.get('head') or '?')[:10]}" if card else ""),
            f"  tickets: {json.dumps(counts)}",
            "  Resume with the status skill (or the migrate skill to continue the pipeline); `forge next` says what is due."]


def main():
    ev = {}
    if not sys.stdin.isatty():
        try:
            ev = json.load(sys.stdin)
        except (json.JSONDecodeError, OSError):
            ev = {}
    ws = find_workspace(ev.get("cwd") or os.getcwd())
    if ws:
        print("\n".join(brief(ws)))


if __name__ == "__main__":
    main()
