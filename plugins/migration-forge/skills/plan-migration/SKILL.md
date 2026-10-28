---
description: Produce the approved migration plan - code-modernization brief, execution waves from the dependency graph, database strategy, acceptance-test plan, and cost projection - for human sign-off before any code is written. Use after the target stack is approved.
argument-hint: (no arguments)
---

# Plan the migration

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

1. Run `F state.py phase plan-migration`. It requires the backlog and stack approvals.
2. **Brief.** Run `/code-modernization:modernize-brief <name> <target from state>`. Make sure `MODERNIZATION_BRIEF.md` reflects the ADR's per-layer track and pinned versions. Edit the brief rather than the ADR if they disagree, and tell the human which one you changed.
3. **Database and cost.** Produce a cost projection yourself as the `cost-assessment` skill describes. There's no pilot data yet, so give a range.
   - When `db_migration` is true, run the `db-migration-engineer` in **plan** mode in parallel. It produces `forge/db/strategy.md` and `map.json`. When the track is off, the plan states "DB unchanged" and lists the ORM/driver settings that map the existing schema.
   - **Behavioral evals run in the Jenkins pipeline.** In `forge/decisions/plan.md`, list the P0 rules and acceptance criteria the pipeline's evals must cover, so its owners can add any that are missing.
4. **Waves.** Order the tickets with `F tracker.py next`. Group them into waves: a wave is a set of tickets with no `blocked_by` between them and no shared `modules`. Write `forge/decisions/plan.md` containing:
   - Wave 0 = the pilot. Choose one P0 module story with few dependencies plus its foundation tickets F1/F2, and F3 when the DB track is on.
   - For each wave: the tickets, the track (uplift/transform/reimagine), the modules, and the acceptance tests.
   - The strangler/cutover approach per layer: route-by-route proxy, feature flags, and the DB switch.
   - The rollback plan for each wave.
   - A risk register: top 5, each with an owner and a mitigation.
5. **Self-check.** Confirm that:
   - every story is in exactly one wave
   - every P0 rule maps to acceptance tests or to a Jenkins eval the pipeline owners have confirmed
   - every DB ticket has a rollback (DB track only)
   - the projected cost is within `cost.max_tokens` (settings), if one is set

   Report any gaps.
6. Commit. Then run the **approve migration** checkpoint. Show the waves, the pilot, the DB strategy in one paragraph, test and eval coverage, the cost range, and the risks.
