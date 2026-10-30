---
name: status
description: Show where a migration run stands - phase, approvals, board counts, latest Jenkins gate verdict and failures, cost so far, and the single next action. Use when the user asks for status/progress of the migration.
argument-hint: (no arguments)
---

`forge` = `"<forge-root>/bin/forge"` (Windows shells: `bin\forge.cmd`). `<forge-root>` is this toolkit's folder: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, otherwise `$FORGE_ROOT` (see `AGENTS.md`).

Run these, then summarize in at most 12 lines:
1. `forge state show`: phase, approvals, iteration, and gate_history.
2. `forge tracker board`, then read `forge/tracker/board.md` for counts per column, blocked tickets, and epic progress.
3. `forge gate show`, if a verdict was imported: the verdict, its build and commit, and the top 3 failures. Say whether HEAD has moved on since, which means a new build is needed.
4. `forge cost --out forge/cost.json`: total tokens against `max_tokens`. If it reports no usage recorded, say spend is unknown.
5. `forge guard legacy`: say if the legacy source has changed since the run started.
6. If `forge/ESCALATION.md` exists, lead with it.

End with **Next:** and one concrete command or decision (`forge next` suggests it).
