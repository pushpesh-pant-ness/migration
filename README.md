# Migration Forge

A standalone migration toolkit. You give it **a story and a legacy repo** (frontend, backend, and a SQL DB). It produces a **migration to a current stack** that your **Jenkins quality-gate pipeline** must pass, plus a local Jira-style backlog.

```
story + repo ─► intake ─► discover ─► plan-stack ─► plan-migration ─► execute (pilot → waves) ─► Jenkins gate ⇄ remediate ─► verify ─► harden ─► done
                 ✋ approve     (review)     ✋ approve       ✋ approve          ✋ "continue" after pilot      auto, max 3 tries          gate      gate ✋ release
```

**It depends on no AI tool and no plugin.** The method is plain Markdown in the open Agent Skills format, the evidence is written by a stdlib-only Python CLI (`forge`), and it runs anywhere Python ≥ 3.9 and git do: Claude Code, other coding agents, a container sandbox, CI, or a human at a terminal. Claude Code is supported through an optional adapter (plugin manifest, hooks, a parallel-wave workflow, evals).

What it covers:
- story → epic/stories/tasks in a local tracker, with Jira CSV export
- built-in playbooks for assessment, topology, business-rule extraction, the modernization brief, uplift/transform/reimagine builds, verification (old-vs-new proof) and security hardening
- target-stack research with pinned, sourced versions
- an optional SQL database-migration track with deterministic parity and reversibility proofs
- a hand-off to the Jenkins pipeline: it imports the pipeline's quality-gate verdict for each commit, and tickets, phases and remediation follow that verdict
- a remediation loop that fixes what Jenkins reports, and is not allowed to weaken the checks

**The quality gates and behavioral evals run in the Jenkins pipeline, not in this toolkit.** That covers static analysis, security, secrets/PII, cost budget and functional evals. Their thresholds belong to the pipeline owners.

## Install

**Prerequisites:** Python ≥ 3.9 (`python3`, `python`, or `py -3`), git. Optional: bash (for `bin/forge`; Windows can use `bin\forge.cmd`), docker, scanners (`forge doctor` lists them). For a private Jenkins, set `JENKINS_USER` and `JENKINS_TOKEN` in your environment.

### Standalone (any agent, sandbox, CI)
Copy or clone `plugins/migration-forge/` anywhere, then:
```bash
export FORGE_ROOT=/path/to/migration-forge   # optional; the CLI finds its own folder
export PATH="$FORGE_ROOT/bin:$PATH"           # optional
forge doctor
```
Point your agent at [`plugins/migration-forge/AGENTS.md`](plugins/migration-forge/AGENTS.md). It explains the CLI, the skills, how to enforce the rules in your host (pre-tool hooks, a git pre-commit hook, a read-only legacy mount in containers), and how to run offline.

### Claude Code plugin
```
/plugin marketplace add "C:/path/to/this/folder"        # or a git URL once you push it
/plugin install migration-forge@migration-forge-marketplace
/migration-forge:setup                                  # checks tools, sets up the Jenkins result URL, offers optional companions
```
No other plugin is required. `code-modernization`, `claude-security`, `context7` and others are optional extras the skills use when present. For development, run `claude --plugin-dir ./plugins/migration-forge`.

## Use
Open an **empty workspace folder**, not the legacy repo.
- **Claude Code:** `/migration-forge:migrate story.md ../legacy-repo "react+nestjs"`
- **Any other agent:** "Follow `<forge-root>/skills/migrate/SKILL.md` with story.md, ../legacy-repo, target react+nestjs."

`forge state init` creates the run, links `legacy/<name>` to your repo, and writes a workspace `AGENTS.md`, so an agent that opens the folder later finds the toolkit and the rules. Run `forge next` at any time to see what is due.

**Database migration is optional and off by default.** By default the existing database is kept exactly as it is, and the new backend connects to the unchanged schema.
- To turn the DB track on (schema/data/engine changes, `forge db` parity and reversibility), add `--with-db`.
- To turn it on mid-run, use `forge state set db_migration true`.
After that, either re-run the `migrate` skill or use the individual phase skills: `intake`, `discover`, `plan-stack`, `plan-migration`, `execute`, `gate`, `remediate`, `verify`, `harden`, `status`, and `tracker`.

## How the Jenkins gate fits in
1. `execute` builds a ticket test-first, commits, and moves the ticket to review.
2. The `gate` skill makes sure Jenkins builds that commit. You push, or start the build. When it finishes, `forge gate import <summary.json path or URL> --commit <sha>` records the verdict in `forge/gates/iteration-N/` and `forge/gates/latest.json`.
   - The location defaults to `jenkins.results_url` in `forge/settings.json`. A local path to a downloaded `summary.json` works too, which is how a sandbox without network access imports it.
   - It reads the pipeline's `results/<phase>/summary.json`, plus the `gate*.json` files and `feedback.md` next to it.
   - The verdict is PASS only when the phase was enforced, every gate passed, and no check was skipped.
   - It refuses a baseline phase, a result already imported, a result for a different commit, and a PASS that doesn't name the commit Jenkins built.
3. **PASS:** tickets close (`tracker` skill rules: PASS for the commit that contains the work). **FAIL:** the `remediate` skill hands each failing gate's `file:line` findings from `feedback.md` to `remediation-engineer` roles. It then commits the fix and goes back to step 2.
   - `forge next` exits 3 on a FAIL until a fix is committed and waiting for a build (in Claude Code the Stop hook enforces it).
   - It escalates after `max_remediation_iterations` (settings) or two identical failures in a row.

## What's inside (`plugins/migration-forge/`)
| Kind | Items |
|------|-------|
| Entry points | `AGENTS.md` (guide for any agent), `bin/forge` and `bin/forge.cmd` (CLI launchers) |
| Skills: phases | `migrate` (orchestrator), `intake`, `discover`, `plan-stack`, `plan-migration`, `execute`, `gate` (import the Jenkins verdict), `remediate`, `verify`, `harden`, `status`, `tracker`, `setup` |
| Skills: knowledge | `sql-db-migration` (+ Postgres/MySQL/SQL Server refs), `cost-assessment`; method references for assessment, the brief and the build tracks |
| Roles | `story-analyst`, `stack-researcher`, `remediation-engineer`, `db-migration-engineer` (only with `--with-db`) |
| Scripts (stdlib Python) | `forge.py` (CLI), `state.py`, `tracker.py`, `jenkins_result.py`, `db_verify.py`, `cost_estimate.py`, `guard.py`, `stop_gate.py`, `session_brief.py`, `doctor.py` |
| Config | `settings.json` (remediation cap, default Jenkins result URL, approvals, token budget), `stack-catalog.json` (approved families + version policy) |
| Claude Code adapter | `.claude-plugin/plugin.json`, `hooks/hooks.json` (guard, stop check, session brief), `workflows/execute-wave.js` (parallel worktree builds + sequential merge), `evals/` (5 `claude plugin eval` cases on the `legacy-shop` fixture) |
| Tests | `tests/` (`python -m unittest discover -s tests`) |

## Workspace a run creates
```
AGENTS.md            points any agent at the toolkit and the rules
legacy/<name>        -> link to your repo (read-only, created by forge state init)
scratch/             disposable copies for legacy builds and scanner output (git-ignored)
analysis/<name>/     ASSESSMENT.md, topology.json, BUSINESS_RULES.md, MODERNIZATION_BRIEF.md, VERIFICATION.md, SECURITY_FINDINGS.md
modernized/          new code (git branches/worktrees per ticket wave)
forge/
  state.json         phase, approvals, legacy fingerprint, gate history (one entry per imported Jenkins verdict)
  story.md
  usage.jsonl        token usage ledger (forge cost log), for tools without readable transcripts
  tracker/           tracker.json · board.md · history.log · epics/ stories/ tasks/ · checklists/ · export/jira-import.csv
  decisions/         ADR-001-target-stack.md · target-stack.json · plan.md · cost-report.md · c4/
  db/                inventory.md · strategy.md · map.json · verify.json   (DB track only)
  evidence/          legacy-security-baseline.json (optional)
  gates/             iteration-N/{summary.json, gate*.json, feedback.md, verdict.json} · latest.json   (imported from Jenkins)
  settings.json      (optional) your overrides: remediation cap, Jenkins result URL, approvals, budget. Only humans edit it
```

## Test the toolkit
```
cd plugins/migration-forge && python -m unittest discover -s tests -v
claude plugin validate ./plugins/migration-forge                   # Claude Code adapter only
cd plugins/migration-forge && claude plugin eval . --scaffold      # Claude Code adapter only
```
Use `--scaffold` because the eval cases seed fixture workspaces with the bash scripts in `evals/`.

## Honest limits
- The toolkit trusts the Jenkins verdict for the commit it names. Pass `--commit` with the SHA the build tested: a PASS without it is refused, and a FAIL without it is recorded as unverified.
- The Claude Code guard resolves the paths a shell command names and blocks changes to `legacy/` and the `forge/` evidence, but it is a tripwire, not a sandbox: a script that builds paths at runtime can get past it. A read-only mount of the legacy repo is the hard boundary.
- The toolkit doesn't run any gate itself, so nothing here stops a schema change while the DB track is off, or a weakened test, until the pipeline or a reviewer catches it. The skills and the remediation role forbid both.
- Outside Claude Code, the guard is only as strong as the host wiring: a pre-tool hook calling `forge guard`, the git pre-commit hook, or a read-only mount. Without them the rules are instructions, and the git history and the Jenkins verdict are what make a violation visible.
- DB checksums compare normalized values across engines. Exotic types (spatial, custom domains) may need an entry in `map.json` with a reason.
- Token USD is never hardcoded. Set `cost.usd_per_mtok` yourself; the USD budget for headless runs is the pipeline's cost gate. Outside Claude Code, token spend is only known if someone logs it with `forge cost log`.
- A large repo plus parallel waves uses a lot of tokens, so the toolkit pilots one module first and asks before fanning out.
