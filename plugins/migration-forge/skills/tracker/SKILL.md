---
description: Work with the local Jira-style tracker (forge/tracker) - show the board, list/next/show tickets, add or link tickets, move status with evidence, validate, and export a Jira CSV (or sync via Atlassian MCP if connected). Use for any epic/story/ticket/board/Jira request inside a migration workspace.
argument-hint: board | next | show <ID> | add ... | move <ID> <status> | link <ID> --blocked-by <ID> | validate | export
---

`T` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" tracker.py`

Map `$ARGUMENTS` to a `T` subcommand. `export` means `export-jira`, and no argument means `board`. Run it and show the output.

## Layout (`forge/tracker/`)
- `tracker.json` is the source of truth. Only the script writes it, and the guard hook blocks hand edits.
- `epics/`, `stories/`, `tasks/` hold one Markdown file per ticket. The front matter belongs to the script. The body (description, acceptance criteria, DoD checkboxes, notes) can be edited.
- `board.md` is the auto-rendered Kanban, and `history.log` is the append-only audit trail.
- `checklists/` holds the per-phase checklists. `export/jira-import.csv` is the file for Jira's CSV importer.

## Rules
- **Status flow:** backlog → ready → in-progress → review → done.
  - Moves into in-progress, review, or done are refused while blockers are open.
  - done is refused while any box is unchecked.
  - `--force` only when the human explicitly asks. Quote them in `--note`.
- **Changing priority, labels, points, or title:** use `T set <ID> --priority P1 --labels a,b --points 5 --title "..."`.
- **Jira:** after `export`, relay the field-mapping line the script prints.
  - If the Atlassian MCP is connected and the user asks to sync, create or update issues from the ticket files.
  - Store each Jira key with `T set <ID> --labels <existing>,jira:<KEY>`.
  - Never delete remote issues.

## Closing a ticket (after a PASS gate)
- **review → done** requires all of these:
  - the latest scorecard says PASS
  - the latest `forge/evidence/gatekeeper-iteration-N.json` says PASS
  - the ticket's eval cases pass in `forge/evals/results.json`
- **Ticking boxes:** edit the ticket body and change `- [ ]` to `- [x]`. Put the proof inline, for example `(evidence: forge/gates/iteration-3/scorecard.json PASS; EV-004 passed)`. Tick a box only when you have read that proof on disk.
- Then run `T move <ID> done --note "<evidence>"`.
