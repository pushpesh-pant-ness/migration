---
description: Execute approved migration tickets test-first - pilot ticket inline, later waves in parallel git worktrees - using code-modernization's uplift/transform/reimagine tracks, then hand each to the Jenkins quality gate. Use after the migration plan is approved, or when the user says to start/continue building.
argument-hint: [pilot | wave <n> | <TICKET-ID>]
---

# Execute

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

Start with `F state.py phase execute`. It needs all three approvals. Then read `forge/decisions/plan.md` to see the waves.

## One ticket (the pilot, a single ID, or any ticket run inline)
1. Run `F tracker.py move <ID> in-progress --note "start"`. The script refuses if the ticket is blocked.
2. **Tests first.** Write or run the ticket's acceptance tests, named after the story id (for example `npx jest -t "STORY-004"` or `pytest -k STORY_004`). Confirm they **fail** for the right reason. A test that already passes before implementation is suspect. If Superpowers is installed, follow `superpowers:test-driven-development`.
3. **Build, using the track from plan.md.**
   - **uplift:** `/code-modernization:modernize-uplift <name> <from> <to>`
   - **transform:** `/code-modernization:modernize-transform <name> <module> <target>`
   - **reimagine:** `/code-modernization:modernize-reimagine <name> <vision>`
   - **DB tickets** (DB track on only): run the `db-migration-engineer` agent in **execute**, then **verify** mode. When the track is off, write no migrations or DDL. If the code can't work without a schema change, move the ticket back with a note and ask the human whether to enable the track.
   - **Framework specifics, when installed:** wshobson `framework-migration` skills (`angular-migration`, `react-modernization`, `dependency-upgrade`, `database-migration`). Use them as reference while transforming.
4. **First build only.** Find where the code landed and record it: `F state.py set modernized_root '"modernized/<dir>"'`.
5. **Go green.** Run the acceptance tests, then the full project test suite. Iterate until both are green.
6. Run `F tracker.py move <ID> review --note "<evidence: test cmd + exit 0>"`, then commit.
7. **Gate.** Run `/migration-forge:gate`: Jenkins runs the quality gates and behavioral evals on the commit, and the skill imports the verdict. If it fails, run `/migration-forge:remediate`. When it passes, close the ticket as the `/migration-forge:tracker` "Closing a ticket" rules describe.

## Pilot rule
Run wave 0 inline, one ticket at a time. After the pilot passes the gate:
1. Produce the cost report as the `cost-assessment` skill describes. This gives the projection from the pilot.
2. Show the human the pilot result: the Jenkins verdict, tokens spent, and projected total.
3. Ask whether to continue with parallel waves.

## Later waves (parallel)
Only after the human says continue. Then:
1. Make sure the working tree is committed.
2. Build `args` from the tracker:
   `{"name": "<name>", "repo": "<abs legacy repo path>", "base_branch": "<current branch>", "plugin_root": "${CLAUDE_PLUGIN_ROOT}", "tickets": [{"id": "STORY-007", "title": "...", "modules": ["orders"], "track": "transform"}]}`
   Include only the tickets of one wave: no `blocked_by` between them and no shared modules.
3. Run the workflow `/migration-forge:execute-wave` with those args. Each ticket builds in its own git worktree on branch `forge/<ID>`, and then a merge step integrates the branches sequentially and runs the full test suite.
4. Read the returned summary. If `full_tests_exit_code` is not 0, fix the merged code before going on. For each ticket the workflow reports as `merged`, move it to review. Then run `/migration-forge:gate` once for the whole wave.
5. Tickets reported `failed` or `conflict` stay in progress. Retry them inline.

Never start the next wave while the current wave's Jenkins verdict is FAIL.
