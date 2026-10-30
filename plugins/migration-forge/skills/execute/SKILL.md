---
name: execute
description: Execute approved migration tickets test-first - pilot ticket inline, later waves in parallel git worktrees - using the built-in uplift/transform/reimagine build tracks, then hand each to the Jenkins quality gate. Use after the migration plan is approved, or when the user says to start/continue building.
argument-hint: [pilot | wave <n> | <TICKET-ID>]
---

# Execute

`forge` = `"<forge-root>/bin/forge"` (Windows shells: `bin\forge.cmd`). `<forge-root>` is this toolkit's folder: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, otherwise `$FORGE_ROOT` (see `AGENTS.md`).

Start with `forge state phase execute`. It needs all three approvals. Then read `forge/decisions/plan.md` to see the waves.

## One ticket (the pilot, a single ID, or any ticket run inline)
1. Run `forge tracker move <ID> in-progress --note "start"`. The script refuses if the ticket is blocked.
2. **Tests first.** Write or run the ticket's acceptance tests, named after the story id (for example `npx jest -t "STORY-004"` or `pytest -k STORY_004`). Confirm they **fail** for the right reason. A test that already passes before implementation is suspect.
3. **Build, using the track from plan.md,** as `<forge-root>/skills/execute/references/build-tracks.md` describes: **uplift**, **transform** or **reimagine**, scoped to the ticket's modules.
   - **DB tickets** (DB track on only): delegate to the `db-migration-engineer` role in **execute**, then **verify** mode. When the track is off, write no migrations or DDL. If the code can't work without a schema change, move the ticket back with a note and ask the human whether to enable the track.
4. **First build only.** Find where the code landed and record it: `forge state set modernized_root '"modernized/<dir>"'`.
5. **Go green.** Run the acceptance tests, then the full project test suite. Iterate until both are green.
6. Run `forge tracker move <ID> review --note "<evidence: test cmd + exit 0>"`, then commit.
7. **Gate.** Follow the `gate` skill: Jenkins runs the quality gates and behavioral evals on the commit, and the skill imports the verdict. If it fails, follow the `remediate` skill. When it passes, close the ticket as the `tracker` skill's "Closing a ticket" rules describe.

## Pilot rule
Run wave 0 inline, one ticket at a time. After the pilot passes the gate:
1. Produce the cost report as the `cost-assessment` skill describes. This gives the projection from the pilot.
2. Show the human the pilot result: the Jenkins verdict, tokens spent, and projected total.
3. Ask whether to continue with parallel waves.

## Later waves (parallel)
Only after the human says continue. Include only the tickets of one wave: no `blocked_by` between them and no shared modules.
1. Make sure the working tree is committed. Note the current branch as `<base>`.
2. **Build each ticket in its own git worktree** (in parallel if your tool runs subagents; one after another otherwise):
   - `git worktree add ../<name>-wt-<ID> -b forge/<ID>`, then in that worktree run `forge state link` so `legacy/<name>` exists there too.
   - Build it as in "One ticket" steps 2, 3 and 5, touching only the ticket's modules. Don't run `forge tracker` or import a verdict there: the orchestrator does that.
   - Commit: `git add -A && git commit -m "forge(<ID>): <title>"`. Report `built` only if the ticket's acceptance tests pass, otherwise `failed`.
3. **Merge sequentially** in the main workspace: `git merge --no-ff forge/<ID>` for each built ticket. If a conflict touches only generated files or lockfiles, resolve it and continue. If it touches source logic, `git merge --abort` and mark that ticket `conflict`.
4. Run the full test suite once. If it is not green, fix the merged code before going on.
5. Move each merged ticket to review. Then follow the `gate` skill once for the whole wave. Tickets that `failed` or hit a `conflict` stay in progress: retry them inline. Remove the worktrees (`git worktree remove`).

In Claude Code, the workflow `workflows/execute-wave.js` automates steps 2–4: run it with args `{"name": "<name>", "repo": "<abs legacy repo path>", "base_branch": "<base>", "plugin_root": "${CLAUDE_PLUGIN_ROOT}", "tickets": [{"id": "STORY-007", "title": "...", "modules": ["orders"], "track": "transform"}]}` and read its summary (`merged`, `failed`, `conflicts`, `full_tests_exit_code`).

Never start the next wave while the current wave's Jenkins verdict is FAIL.
