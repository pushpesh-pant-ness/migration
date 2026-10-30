---
name: discover
description: Discover a legacy codebase for migration - baseline build, architecture, features, business rules, dependencies, C4 diagrams and SQL database inventory - with the built-in assessment method, mapped onto the local backlog. Use after intake, or when the user asks to analyse/assess/map a legacy repo.
argument-hint: (no arguments; uses forge/state.json)
---

# Discover

`forge` = `"<forge-root>/bin/forge"` (Windows shells: `bin\forge.cmd`). `<forge-root>` is this toolkit's folder: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, otherwise `$FORGE_ROOT` (see `AGENTS.md`).

Read `<name>`, `repo`, and `target` from `forge state show`. Then run `forge state phase discover`.

## Steps
1. **Assess.** Make sure `legacy/<name>` exists (`forge state link` re-creates it). Then follow `<forge-root>/skills/discover/references/assessment-method.md` in order. It writes, under `analysis/<name>/`:
   - `ASSESSMENT.md` (baseline build and tests, inventory, recommended track per layer)
   - `topology.json` and `topology.mmd`
   - `BUSINESS_RULES.md`, with the human review of the P0 rules
2. **C4 diagrams.** Derive Mermaid C4 context and container diagrams from `topology.json` (or use a C4 skill if your tool has one). Write them to `forge/decisions/c4/{context,container}.md`.
3. **Database** (only when `db_migration` is true in state). Delegate to the `db-migration-engineer` role in **inventory** mode. It sets `has_database false` when there is no SQL database. When the track is off, skip this step. Just note the DB engine and version from `ASSESSMENT.md` so the stack researcher can check driver compatibility against the unchanged server.
4. **Run these together** (in parallel if your tool can):
   - delegate to the `stack-researcher` role in *current-stack inventory only* mode. It confirms the exact current versions and their EOL status, and does **not** propose a target yet. It writes `forge/decisions/current-stack.md`.
   - optional: follow the `harden` skill in **legacy-baseline** mode, so you know which vulnerabilities must not be carried over. It writes `forge/evidence/legacy-security-baseline.json`.
5. **Refine the backlog.** Delegate to the `story-analyst` role in refinement pass mode. It reads all of the above, adds module stories mapped to BR ids, and records `blocked_by` edges. Then run `forge tracker validate`, which must exit 0, and `forge tracker board`.
6. **Close out.** Tick the items you completed in `forge/tracker/checklists/discovery.md`. Commit. Then report in at most 15 lines:
   - module count
   - P0 rules, and any still `needs-review`
   - EOL components
   - DB size and complexity
   - top risks
   - the critical path
   - next step: plan-stack

Large repos: if `topology.json` has more than about 15 modules, propose a pilot slice to the human before deep extraction of every module. Use one P0 module plus its dependencies.
