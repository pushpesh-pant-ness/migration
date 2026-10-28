---
description: Discover a legacy codebase for migration - architecture, features, business rules, dependencies, C4 diagrams and SQL database inventory - by driving Anthropic's code-modernization assessment and mapping it onto the local backlog. Use after intake, or when the user asks to analyse/assess/map a legacy repo.
argument-hint: (no arguments; uses forge/state.json)
---

# Discover

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

Read `<name>`, `repo`, and `target` from `F state.py show`. Then run `F state.py phase discover`.

## Steps
1. **Preflight and assess with code-modernization.** If those commands are missing, follow its README manually.
   - `/code-modernization:modernize-preflight <name> <target> --source <repo>`. This creates the `legacy/<name>` link. If the link is a symlink, follow the instructions it prints about `additionalDirectories` and deny rules.
   - `/code-modernization:modernize-assess <name>`, which writes `ASSESSMENT.md`.
   - `/code-modernization:modernize-map <name>`, which writes `topology.json` and `TOPOLOGY.html`.
   - `/code-modernization:modernize-extract-rules <name>`, which writes `BUSINESS_RULES.md`. Then run `/code-modernization:modernize-review <name>`, so a human confirms the P0 rules.
2. **C4 diagrams.** If the wshobson `c4-architecture` plugin is installed, use its `c4-context` and `c4-container` agents. Otherwise derive Mermaid C4 from `topology.json`. Write the result to `forge/decisions/c4/{context,container}.md`.
3. **Database** (only when `db_migration` is true in state). Run the `db-migration-engineer` agent in **inventory** mode. It sets `has_database false` when there is no SQL database. When the track is off, skip this step. Just note the DB engine and version from `ASSESSMENT.md` so the stack-researcher can check driver compatibility against the unchanged server.
4. **Run these together.** In a single message, delegate:
   - the `stack-researcher` agent in *current-stack inventory only* mode. It confirms the exact current versions and their EOL status, and does **not** propose a target yet. It writes `forge/decisions/current-stack.md`.
   - optional: `/claude-security` "scan codebase" on `legacy/<name>`, as a **baseline**. The point is to know which vulnerabilities must not be carried over. Save its summary as `forge/evidence/legacy-security-baseline.json`.
5. **Refine the backlog.** Run the `story-analyst` agent in refinement pass mode. It reads all of the above, adds module stories mapped to BR ids, and records `blocked_by` edges. Then run `F tracker.py validate`, which must exit 0, and `F tracker.py board`.
6. **Close out.** Tick the items you completed in `forge/tracker/checklists/discovery.md`. Commit. Then report in at most 15 lines:
   - module count
   - P0 rules
   - EOL components
   - DB size and complexity
   - top risks
   - the critical path
   - next step: plan-stack

Large repos: if `topology.json` has more than about 15 modules, propose a pilot slice to the human before deep extraction of every module. Use one P0 module plus its dependencies.
