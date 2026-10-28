# Migration Forge

A Claude Code plugin you install and run. You give it **a story and a legacy repo** (frontend, backend, and a SQL DB). It produces a **migration to a current stack** that your **Jenkins quality-gate pipeline** must pass, plus a local Jira-style backlog.

```
story + repo ─► intake ─► discover ─► plan-stack ─► plan-migration ─► execute (pilot → waves) ─► Jenkins gate ⇄ remediate ─► verify ─► harden ─► done
                 ✋ approve     (review)     ✋ approve       ✋ approve          ✋ "continue" after pilot      auto, max 3 tries          gate      gate ✋ release
```

It **orchestrates** Anthropic's `code-modernization` plugin and adds what that plugin doesn't cover:
- story → epic/stories/tasks in a local tracker, with Jira CSV export
- target-stack research with pinned, sourced versions
- an optional SQL database-migration track with deterministic parity and reversibility proofs
- a hand-off to the Jenkins pipeline: it imports the pipeline's quality-gate verdict for each commit, and tickets, phases and remediation follow that verdict
- a remediation loop that fixes what Jenkins reports, and is not allowed to weaken the checks

**The quality gates and behavioral evals run in the Jenkins pipeline, not in this plugin.** That covers static analysis, security, secrets/PII, cost budget and functional evals. Their thresholds belong to the pipeline owners.

## Install
Run these in Claude Code (CLI, desktop, or IDE):
```
/plugin marketplace add "C:/path/to/this/folder"        # or a git URL once you push it
/plugin install migration-forge@migration-forge-marketplace
/migration-forge:setup                                  # checks tools, sets up the Jenkins result URL, offers optional companions
```
The required dependencies install automatically from `claude-plugins-official`: `code-modernization`, `claude-security`, `security-guidance`, and `context7`.

**Prerequisites:**
- Python ≥ 3.9 (`python3`, `python`, or `py -3`)
- bash (Git Bash on Windows) for the hooks
- git
- access to the Jenkins pipeline's build artifacts. For a private Jenkins, set `JENKINS_USER` and `JENKINS_TOKEN` in your environment.

For development, run `claude --plugin-dir ./plugins/migration-forge`.

## Use
Open an **empty workspace folder**, not the legacy repo, and run:
```
/migration-forge:migrate story.md ../legacy-repo "react+nestjs"
```
**Database migration is optional and off by default.** By default the existing database is kept exactly as it is, and the new backend connects to the unchanged schema.
- To turn the DB track on (schema/data/engine changes, `db_verify` parity and reversibility), add `--with-db`.
- To turn it on mid-run, use `state.py set db_migration true`.
After that, either re-run `/migration-forge:migrate` or use the individual phase commands: `intake`, `discover`, `plan-stack`, `plan-migration`, `execute`, `gate`, `remediate`, `status`, and `tracker`.

## How the Jenkins gate fits in
1. `execute` builds a ticket test-first, commits, and moves the ticket to review.
2. `/migration-forge:gate` makes sure Jenkins builds that commit. You push, or start the build. When it finishes, `jenkins_result.py import <summary.json path or URL> --commit <sha>` records the verdict in `forge/gates/iteration-N/` and `forge/gates/latest.json`.
   - The location defaults to `jenkins.results_url` in `forge/settings.json`.
   - It reads the pipeline's `results/<phase>/summary.json`, plus the `gate*.json` files and `feedback.md` next to it.
   - The verdict is PASS only when the phase was enforced, every gate passed, and no check was skipped.
   - It refuses a baseline phase, a result already imported, and a result for a different commit.
3. **PASS:** tickets close (`/migration-forge:tracker` rules: PASS for the commit that contains the work). **FAIL:** `/migration-forge:remediate` hands each failing gate's `file:line` findings from `feedback.md` to `remediation-engineer` agents. It then commits the fix and goes back to step 2.
   - The Stop hook keeps the session working on a FAIL until a fix is committed, then lets it wait for the next build.
   - It escalates after `max_remediation_iterations` (settings) or two identical failures in a row.

## What's inside (`plugins/migration-forge/`)
| Kind | Items |
|------|-------|
| Skills: user commands | `migrate` (orchestrator), `intake`, `discover`, `plan-stack`, `plan-migration`, `execute`, `gate` (import the Jenkins verdict), `remediate`, `status`, `tracker`, `setup` |
| Skills: model knowledge | `sql-db-migration` (+ Postgres/MySQL/SQL Server refs), `cost-assessment` |
| Agents | `story-analyst`, `stack-researcher`, `remediation-engineer`, `db-migration-engineer` (only with `--with-db`) |
| Workflows | `execute-wave` (parallel worktree builds + sequential merge) |
| Hooks | `guard` (legacy read-only; script-owned evidence, verdicts and state; human-owned settings; **approvals and `--force` always raise a permission prompt you must click**), `stop_gate` (no stopping on a failing Jenkins verdict while budget remains, unless a fix is committed and waiting for a build), `session_brief` |
| Scripts (stdlib Python) | `state.py`, `tracker.py`, `jenkins_result.py`, `db_verify.py`, `cost_estimate.py`, `doctor.py` |
| Config | `settings.json` (remediation cap, default Jenkins result URL, token budget), `stack-catalog.json` (approved families + version policy) |
| Tests | `tests/test_jenkins_result.py` (verdict import, stop hook, guard; `python -m unittest discover -s tests`) |
| Evals | 5 fast `claude plugin eval` cases (intake, tracker export, guard, refusing "done" on a FAIL verdict, DB method) on the `legacy-shop` fixture |

## Workspace a run creates
```
legacy/<name>        -> link to your repo (read-only, created by code-modernization preflight)
analysis/<name>/     ASSESSMENT.md, topology.json, BUSINESS_RULES.md, MODERNIZATION_BRIEF.md, VERIFICATION.md, SECURITY_FINDINGS.md
modernized/          new code (git branches/worktrees per ticket wave)
forge/
  state.json         phase, approvals, gate history (one entry per imported Jenkins verdict)
  story.md
  tracker/           tracker.json · board.md · history.log · epics/ stories/ tasks/ · checklists/ · export/jira-import.csv
  decisions/         ADR-001-target-stack.md · target-stack.json · plan.md · cost-report.md · c4/
  db/                inventory.md · strategy.md · map.json · verify.json   (DB track only)
  evidence/          legacy-security-baseline.json (optional)
  gates/             iteration-N/{summary.json, gate*.json, feedback.md, verdict.json} · latest.json   (imported from Jenkins)
  settings.json      (optional) your overrides: remediation cap, Jenkins result URL, budget. Only humans edit it
```

## Test the plugin
```
claude plugin validate ./plugins/migration-forge
cd plugins/migration-forge && python -m unittest discover -s tests -v
cd plugins/migration-forge && claude plugin eval . --scaffold
```
Use `--scaffold` because the cases seed fixture workspaces with the bash scripts in `evals/`.

## Honest limits
- The plugin trusts the Jenkins verdict for the commit it names. Pass `--commit` with the SHA the build tested; without it the import records the verdict as unverified.
- The plugin doesn't run any gate itself, so nothing here stops a schema change while the DB track is off, or a weakened test, until the pipeline or a reviewer catches it. The skills and the remediation agent forbid both.
- DB checksums compare normalized values across engines. Exotic types (spatial, custom domains) may need an entry in `map.json` with a reason.
- Token USD is never hardcoded. Set `cost.usd_per_mtok` yourself; the USD budget for headless runs is the pipeline's cost gate.
- A large repo plus parallel waves uses a lot of tokens, so the plugin pilots one module first and asks before fanning out.
