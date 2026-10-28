---
description: Show where a migration run stands - phase, approvals, board counts, latest gate verdict and failures, cost so far, and the single next action. Use when the user asks for status/progress of the migration.
argument-hint: (no arguments)
---

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

Run these, then summarize in at most 12 lines:
1. `F state.py show`: phase, approvals, iteration, and gate_history.
2. `F tracker.py board`, then read `forge/tracker/board.md` for counts per column, blocked tickets, and epic progress.
3. Read `forge/gates/latest.json`, if it exists: verdict, overall score, and the top 3 failures.
4. `F cost_estimate.py --out forge/cost.json`: total tokens against `checks.cost.max_tokens`.
5. If `forge/ESCALATION.md` exists, lead with it.

End with **Next:** and one concrete command or decision.
