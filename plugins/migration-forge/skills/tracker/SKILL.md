---
name: tracker
description: Work with the local Jira-style tracker (forge/tracker) - show the board, list/next/show tickets, add or link tickets, move status with evidence, validate, and export a Jira CSV (or sync through a Jira connector if one is available). Use for any epic/story/ticket/board/Jira request inside a migration workspace.
argument-hint: board | next | show <ID> | add ... | move <ID> <status> | link <ID> --blocked-by <ID> | validate | export
---

`forge` = `"<forge-root>/bin/forge"` (Windows shells: `bin\forge.cmd`). `<forge-root>` is this toolkit's folder: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, otherwise `$FORGE_ROOT` (see `AGENTS.md`). `T` = `forge tracker`.

Map the request (`$ARGUMENTS`) to a `T` subcommand. `export` means `export-jira`, and no argument means `board`. Run it and show the output.

## Layout (`forge/tracker/`)
- `tracker.json` is the source of truth. Only the script writes it, and the guard blocks hand edits.
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
  - If a Jira connector is available in your tool (for example the Atlassian MCP server) and the user asks to sync, create or update issues from the ticket files.
  - Store each Jira key with `T set <ID> --labels <existing>,jira:<KEY>`.
  - Never delete remote issues.

## Closing a ticket (after a PASS from Jenkins)
- **review → done** requires all of these:
  - `forge/gates/latest.json` says PASS, with `source` jenkins and `commit_verified` true
  - its `head` is the current commit (`git rev-parse HEAD`), or an ancestor that already contains this ticket's work with only `forge/` changes since, and `workspace_dirty` is false (that flag ignores `forge/`, so it means uncommitted code). `forge next` says "PASSED for the current code" exactly when this holds.
  - the ticket's acceptance tests pass
- **Ticking boxes:** edit the ticket body and change `- [ ]` to `- [x]`. Put the proof inline, for example `(evidence: forge/gates/iteration-3/verdict.json PASS, build #42, commit abc1234)`. Tick a box only when you have read that proof on disk.
- Then run `T move <ID> done --note "<evidence>"`.
