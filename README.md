# Migration Forge

A Claude Code plugin you install and run. You give it **a story and a legacy repo** (frontend, backend, and a SQL DB). It produces a **gated, verified migration** to a current stack, plus a local Jira-style backlog.

```
story + repo ─► intake ─► discover ─► plan-stack ─► plan-migration ─► execute (pilot → waves) ─► gate ⇄ remediate ─► verify ─► harden ─► done
                 ✋ approve     (review)     ✋ approve       ✋ approve          ✋ "continue" after pilot     auto, max 3 tries     gate      gate ✋ release
```

It **orchestrates** Anthropic's `code-modernization` plugin and adds what that plugin doesn't cover:
- story → epic/stories/tasks in a local tracker, with Jira CSV export
- target-stack research with pinned, sourced versions
- an optional SQL database-migration track with deterministic parity and reversibility proofs
- behavioral evals
- a scored quality/security/cost gate that blocks progress
- a remediation loop that is not allowed to weaken the checks

## Install
Run these in Claude Code (CLI, desktop, or IDE):
```
/plugin marketplace add "C:/path/to/this/folder"        # or a git URL once you push it
/plugin install migration-forge@migration-forge-marketplace
/migration-forge:setup                                  # checks semgrep/gitleaks/trivy etc., offers optional companions
```
The required dependencies install automatically from `claude-plugins-official`: `code-modernization`, `claude-security`, `security-guidance`, and `context7`.

**Prerequisites:**
- Python ≥ 3.9 (`python3`, `python`, or `py -3`)
- bash (Git Bash on Windows) for the hooks
- git

For development, run `claude --plugin-dir ./plugins/migration-forge`.

## Use
Open an **empty workspace folder**, not the legacy repo, and run:
```
/migration-forge:migrate story.md ../legacy-repo "react+nestjs"
```
**Database migration is optional and off by default.** By default the existing database is kept exactly as it is, and the new backend connects to the unchanged schema. The gatekeeper fails any DDL added while the track is off.
- To turn the DB track on (schema/data/engine changes, `db_verify` parity and reversibility, the database gate), add `--with-db`.
- To turn it on mid-run, use `state.py set db_migration true`.
After that, either re-run `/migration-forge:migrate` or use the individual phase commands: `intake`, `discover`, `plan-stack`, `plan-migration`, `execute`, `gate`, `remediate`, `status`, and `tracker`.

## What's inside (`plugins/migration-forge/`)
| Kind | Items |
|------|-------|
| Skills: user commands | `migrate` (orchestrator), `intake`, `discover`, `plan-stack`, `plan-migration`, `env` (side-by-side runtime), `execute`, `gate`, `remediate`, `ci` (generate a pipeline that enforces the gate), `status`, `tracker`, `setup` |
| Skills: model knowledge | `sql-db-migration` (+ Postgres/MySQL/SQL Server refs), `migration-evals`, `cost-assessment` |
| Agents | `story-analyst`, `stack-researcher`, `env-provisioner`, `eval-designer`, `gatekeeper` (read-only), `remediation-engineer`, `db-migration-engineer` (only with `--with-db`) |
| Workflows | `execute-wave` (parallel worktree builds + sequential merge), `gate-loop` (gate → audit → fix → re-gate) |
| Hooks | `guard` (legacy read-only; script-owned evidence and state; human-owned thresholds; **approvals and `--force` always raise a permission prompt you must click**), `stop_gate` (no stopping on a failing gate while budget remains), `session_brief` |
| Scripts (stdlib Python) | `state.py`, `tracker.py`, `run_gates.py` + `score.py`, `env.py`, `evals_run.py`, `db_verify.py`, `cost_estimate.py`, `doctor.py` |
| Config | `gates.json` (thresholds), `stack-catalog.json` (approved families + version policy) |
| Evals | 5 fast `claude plugin eval` cases + 1 nightly end-to-end pilot (`e2e-pilot-fixture`, tag `e2e`) on the `legacy-shop` fixture (Express 4 + jQuery 1.12 + MySQL 5.7 with planted issues) |

## Workspace a run creates
```
legacy/<name>        -> link to your repo (read-only, created by code-modernization preflight)
analysis/<name>/     ASSESSMENT.md, topology.json, BUSINESS_RULES.md, MODERNIZATION_BRIEF.md, VERIFICATION.md, SECURITY_FINDINGS.md
modernized/          new code (git branches/worktrees per ticket wave)
forge/
  state.json         phase, approvals, gate history
  story.md
  tracker/           tracker.json · board.md · history.log · epics/ stories/ tasks/ · checklists/ · export/jira-import.csv
  decisions/         ADR-001-target-stack.md · target-stack.json · plan.md · cost-report.md · c4/
  db/                inventory.md · strategy.md · map.json · verify.json   (DB track only)
  env/               docker-compose.yml · seed/ · env.json   (legacy :18080 and new :28080, each with its own seeded data)
  evals/             cases.json · coverage.md · results.json · ui/ (Playwright parity specs + golden screenshots from legacy)
  evidence/          claude-security.json · gatekeeper-iteration-N.json
  gates/             iteration-N/{scorecard.json, raw/*} · latest.json
  gates.json         (optional) your threshold overrides. Only humans edit it
```

## Gate defaults (`config/gates.json`)
A required check that **cannot run fails**. Nothing passes silently. The verdict is PASS only when every required check passes **and** the overall score is at least 85.

| Check | Evidence | Pass when |
|-------|----------|-----------|
| tests | project test command (+JUnit XML) | 0 failing, ≥1 ran |
| coverage | lcov / Cobertura / JaCoCo (+ diff-cover since `base_ref`); Istanbul / coverage.py summaries for overall only | changed lines ≥ 80% (falls back to overall ≥ 70% when diff coverage can't be measured) |
| review | built-in `/code-review` + code-modernization `architecture-critic` (ADR drift, ported anti-patterns) on the diff since `base_ref` | 0 blocking, ≤ 5 major |
| typecheck / lint | tsc, mypy, or the project script / eslint, ruff | 0 errors (lint optional) |
| security | Semgrep, gitleaks, Trivy (vuln/secret/misconfig/**licence**), npm audit, pip-audit + claude-security verified findings | 0 critical, 0 high, 0 secrets, 0 forbidden/restricted licences |
| behavior | VERIFICATION.md verdicts + `evals_run.py` against the side-by-side env (golden-master HTTP diff, **Playwright UI parity** that must pass on legacy first, acceptance tests; SQL diff on the DB track) | 0 NOT/PARTLY PROVEN, 100% evals |
| database (only with `--with-db`) | `db_verify.py` row counts + order-independent checksums; up/down/up; squawk | 100% match, reversible (n/a when off) |
| cost | tokens from transcripts; Infracost on IaC | within budget you set |
| performance (opt.) | k6 summary vs legacy | p95 regression ≤ 10% |

The `gatekeeper` agent then audits the evidence itself. It looks for skipped tests, added suppressions, stale coverage files, edited thresholds, and modules not covered. It can turn a PASS into a FAIL.

## Test the plugin
```
claude plugin validate ./plugins/migration-forge
cd plugins/migration-forge && claude plugin eval . --scaffold
```
Use `--scaffold` because the cases seed fixture workspaces with the bash scripts in `evals/`.

The end-to-end pilot is slow and expensive: it runs a full pilot, needs the dependency plugins and Docker, and takes up to an hour. Run it nightly, not on every change:
```
claude plugin eval . --scaffold --tag e2e
```
Skip it in fast runs by selecting the other cases with `--tag smoke --tag guardrail`. That case sets `EVAL_FORGE_AUTO_APPROVE=1` so approval prompts don't block a headless run. Never set it in a real session.

## CI
`/migration-forge:ci` vendors the gate scripts into `.forge-ci/` and writes `.github/workflows/forge-gates.yml`. Azure DevOps or GitLab are available on request. It pins tool versions it fetched at generation time. The pipeline checks out the frozen legacy commit, starts both apps, runs the evals, and runs `run_gates.py` at the same thresholds. Only the checks that need Claude (the claude-security summary, the code review, and token cost) are relaxed, via `.forge-ci/gates.ci.json`. To restore them, enable the optional `claude-evidence` job.

## Honest limits
- "Best" is proven per codebase. Run the pilot, read the scorecard, and tune `forge/gates.json`.
- Changed-line coverage needs `diff-cover` and an lcov or XML report. Path mapping between the report and git can differ by stack, so check `raw/diff-cover.json` on the first gate. If it can't be measured, the gate says so and falls back to overall coverage.
- The `review` and claude-security counts are produced by a model. The gatekeeper cross-checks them against the findings list, but they are not deterministic.
- Lint and typecheck error counts from custom scripts are approximate (exit code plus a pattern count).
- DB checksums compare normalized values across engines. Exotic types (spatial, custom domains) may need an entry in `map.json` with a reason.
- Infra cost is gated only when IaC and Infracost exist. Otherwise it is a labeled estimate.
- Token USD is never hardcoded. Set `cost.usd_per_mtok` yourself.
- A large repo plus parallel waves uses a lot of tokens, so the plugin pilots one module first and asks before fanning out.
