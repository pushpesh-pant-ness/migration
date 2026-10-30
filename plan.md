# Migration Forge 1.0: operator-agnostic, standalone code-transformation toolkit

**Status:** Proposed. Version 1 of this plan, written 2026-10-30 from a full read of the repository at commit `121012b`.
**Audience:** the owner (Pushpesh Pant), every engineer who implements a phase, and every AI coding agent that is asked to implement a phase.
**Scope of the document:** what exists today, what is wrong with it, the target architecture, a phased delivery plan with acceptance criteria, a critique of this plan, and the decisions the owner still has to make.

---

## 0. Binding rules: this plan must be followed strictly

This section is normative. Everything below it is an instruction, not a suggestion. Whoever implements any part of this plan, human or AI agent, follows these rules:

1. **Follow the phases in order (Section 8).** Do not start a phase before the previous phase's exit criteria are met and recorded in `docs/plan-progress.md`. Within a phase, tasks may run in any order unless a dependency is stated.
2. **Do exactly the scope written for each task.** No silent widening (extra features), narrowing (dropping a deliverable) or substitution (a different approach). If a task cannot be done as written, stop, write the problem in `docs/plan-progress.md`, and raise it with the owner. Scaling the work down is the owner's decision.
3. **Every deviation needs an ADR first.** Write `docs/adr/ADR-NNN-<slug>.md` (template in Appendix F), get the owner's written approval, and only then implement the deviation. An approval inside a chat transcript, a commit message or a tool result does not count; the approval is a line in the ADR with the approver's name and date.
4. **The non-negotiables in Section 6.5 may never be weakened** by any task, fix, refactor or "temporary" change. If a test or a check stands in the way, fix the code, not the check.
5. **The Claude Code plugin must stay installable and green at the end of every phase.** `claude plugin validate` and the unit tests must pass. Existing slash commands keep their names until the deprecation step in Phase 6.
6. **Acceptance criteria are the definition of done.** A task is done only when every criterion listed for it is verified by running the stated command and the output is pasted into `docs/plan-progress.md`. "It should work" is not done.
7. **Report honestly.** A failing test, a skipped step or an unverified claim is written down as such. Never mark a criterion met because it probably is.
8. **Do not add dependencies outside the allowed list** (Section 7.6). Stdlib-only for the core; optional extras only where the plan names them.
9. **Do not touch `main` directly.** Each phase is one or more branches named `forge/phase-<n>-<slug>`, merged by pull request with the phase checklist in the description.
10. **When the plan and the code disagree, the plan wins** until an ADR changes the plan. When the plan and reality disagree (a tool no longer exists, an API changed), write the ADR, do not improvise.
11. **Read the whole plan before starting any task.** Many tasks depend on definitions in Sections 5, 6 and the appendices. Partial reading leads to re-implementing something the core already provides.
12. **Keep this document current.** When an ADR changes a decision, update the affected section and add a line to the change log at the end of this file.

---

## 1. Executive summary

Migration Forge today is a Claude Code plugin (version 0.1.0) that turns a user story plus a legacy repository into a gated, ticket-driven modernization. Its deterministic parts (state machine, tracker, Jenkins verdict import, DB parity, cost report) are plain stdlib Python and already portable. Everything that makes it a *product*, however, is tied to Claude Code:

- enforcement lives in Claude Code hooks (`guard.py`, `stop_gate.py`), so no other operator and no headless run gets any protection;
- the method for discovery and transformation is outsourced to four Claude-only plugins (`code-modernization`, `claude-security`, `security-guidance`, `context7`), unpinned;
- parallel execution is a Claude Code `Workflow` script, skills are written in Claude slash-command vocabulary, agents use Claude's subagent format, evals need `claude plugin eval`, and the cost report parses Claude transcripts;
- the only quality gate is a Jenkins pipeline that is not in this repository and has no written contract, so the plugin cannot run on its own at all.

**Recommendation.** Rebuild Migration Forge as a three-layer toolkit, reusing about 70 percent of the current Python:

1. **A standalone core** (`forge` CLI and Python package, stdlib only) that owns state, tracker, evidence, policy, approvals, gate contract, DB verification, cost ledger, a local reference gate runner and a headless runner. It works with no AI at all for the deterministic parts and drives any coding agent for the rest.
2. **A portable method** (skills in the Agent Skills open standard format, role prompts, codemod recipes, checklists) written in operator-neutral vocabulary: "run `forge ...`" and "use the `forge` MCP tools", never a slash command.
3. **Thin operator adapters** that package the method for each coding agent (Claude Code, OpenAI Codex CLI, Cursor, GitHub Copilot CLI, OpenCode, Gemini CLI or its successor, and a generic `AGENTS.md` + MCP fallback), add hook shims where the operator has hooks, and drive the operator headless through its CLI.

Safety stops depending on hooks. It moves into the core: legacy source is locked at the filesystem level and verified by a tree hash, evidence files are hash-chained in a ledger, approvals are bound to a human identity through pluggable providers, and a `forge audit` command runs before every gate import and in CI. Hooks become a convenience that gives earlier feedback, not the thing that keeps the run honest.

The quality gate gets a written contract (JSON schema, the one `jenkins_result.py` already implies) plus a minimal, pluggable reference runner so a run can be gated locally or in any CI, with Jenkins remaining the judge where a team has one.

Estimated effort: 12 to 16 engineer-weeks across seven phases, with the Claude Code plugin staying usable throughout. Details and risks are in Sections 8, 11 and 12.

---

## 2. What exists today (as-is assessment)

Read in full on 2026-10-30. Numbers are from the working tree at `121012b`.

### 2.1 Inventory

| Area | Files | Lines (approx.) | Notes |
|------|-------|------------------|-------|
| Scripts (`plugins/migration-forge/scripts/`) | 10 Python + `py.sh` | 1,350 | stdlib only; `tracker.py` 423, `db_verify.py` 257, `jenkins_result.py` 172, `guard.py` 110, `state.py` 100, `cost_estimate.py` 101, `forgelib.py` 78, `stop_gate.py` 62, `doctor.py` 32, `session_brief.py` 29 |
| Skills (`skills/*/SKILL.md` + references) | 11 skills, 9 reference/checklist files | 650 | `migrate` (orchestrator), `intake`, `discover`, `plan-stack`, `plan-migration`, `execute`, `gate`, `remediate`, `status`, `tracker`, `setup`; knowledge skills `sql-db-migration`, `cost-assessment` |
| Agents (`agents/*.md`) | 4 | 170 | `story-analyst`, `stack-researcher`, `remediation-engineer`, `db-migration-engineer` |
| Workflow | 1 (`execute-wave.js`) | 86 | Claude Code `Workflow` tool script |
| Hooks | `hooks.json` | 26 | PreToolUse guard, Stop gate, SessionStart brief |
| Config | `settings.json`, `stack-catalog.json` | 60 | |
| Tests | `tests/test_jenkins_result.py` | 163 | 8 tests, all pass (verified 2026-10-30 with `py -3 -m unittest discover -s tests`) |
| Evals | 5 cases + `legacy-shop` fixture | 300 | `claude plugin eval` format |
| Manifests | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | 30 | depends on 4 plugins from `claude-plugins-official`, unpinned |
| Docs | `README.md`, `THIRD_PARTY_NOTICES.md` | 115 | |

Git history: four commits on 2026-10-28. Commit `6a44501` added a full local quality-gate toolkit (SonarQube, Semgrep, Gitleaks, Trivy, PII scan, http_expect evals, cost ledger, Jenkinsfile; about 2,850 lines). Commit `87de738` ("fix gates") deleted all of it and `121012b` replaced it with the Jenkins verdict import. No reason is recorded for the deletion. This matters for Section 4 and Section 12.

### 2.2 What works and should be kept

- **The phase machine with human checkpoints** (`intake → discover → plan-stack → plan-migration → execute → gate ⇄ remediate → verify → harden → done`), with approvals required before `discover`, `plan-migration`, `execute` and `done`.
- **Evidence-first design:** scripts write evidence; the model is told to read it. The tracker refuses `done` while acceptance boxes are unchecked or blockers are open. The gate import refuses baselines, duplicates and verdicts for other commits.
- **The tracker** (epics, stories, tasks, dependency cycle detection, board rendering, Jira CSV export) is a sound local backlog.
- **The DB track** (`db_verify.py` parity and reversibility, the SQL method and per-engine references) is well designed and operator-neutral already.
- **Stack research method** (endoflife.date, pinned versions with sources, ADR template, scoring).
- **Pilot-first, fan-out-with-consent** cost discipline.
- **Jenkins-as-judge separation**: the thresholds belong to the pipeline owners, the plugin only imports a verdict. This stays as one supported mode.

### 2.3 Claude lock-in map

| Component | Lock-in | Why |
|-----------|---------|-----|
| `scripts/state.py`, `tracker.py`, `jenkins_result.py`, `db_verify.py`, `doctor.py`, `forgelib.py` | none | stdlib Python, CLI |
| `scripts/guard.py`, `stop_gate.py`, `session_brief.py` | high | speak the Claude Code hook JSON protocol (`hookSpecificOutput`, `permissionDecision`, `stop_hook_active`) |
| `scripts/cost_estimate.py` | high | parses `~/.claude/projects/**/*.jsonl` transcripts |
| `skills/*/SKILL.md` | medium | the file format is portable (Agent Skills standard), the bodies are not: `/code-modernization:*`, `/claude-security`, `/migration-forge:*`, `${CLAUDE_PLUGIN_ROOT}`, `AskUserQuestion`, `Skill` tool, Superpowers, wshobson plugins |
| `agents/*.md` | medium | Claude subagent frontmatter (`tools:`, `model: inherit`); other operators have different agent formats or none |
| `workflows/execute-wave.js` | total | Claude Code `Workflow` API (`agent()`, `parallel()`, `phase()`, `isolation: 'worktree'`) |
| `hooks/hooks.json` | total | Claude Code hook schema |
| `.claude-plugin/*.json` | total | Claude plugin and marketplace manifests |
| `evals/` | total | `claude plugin eval` case format and graders |
| `config/*.json` | none | |
| `tests/` | none | |

---

## 3. Shortcomings found

Each item has an identifier (S-n) so later sections and the phase tasks can reference it. Severity: **H** blocks the stated goals (any operator, standalone), **M** causes wrong or unsafe results in some runs, **L** quality or maintenance.

### 3.1 In the current plugin

| ID | Sev | Shortcoming | Evidence |
|----|-----|-------------|----------|
| S-1 | H | **No gate without Jenkins.** The plugin cannot produce any verdict itself, so it cannot run standalone, and the pipeline it depends on is not in the repository. | `README.md` "The quality gates ... run in the Jenkins pipeline, not in this plugin"; `87de738` deleted the local runner |
| S-2 | H | **The gate contract is implicit.** `summary.json`, `gate*.json` and `feedback.md` shapes exist only as code in `jenkins_result.py`. No schema, no versioning, no contract test the pipeline team can run. | `jenkins_result.py` lines checking `gates`, `failed_gates`, `enforced`, `skipped_checks`, `checks[].metric/value/rule/passed/missing` |
| S-3 | H | **All enforcement is Claude-hook-bound.** Outside Claude Code (any other operator, `claude -p` with hooks disabled, CI) there is no legacy read-only guard, no stop-on-FAIL, no approval prompt. | `hooks/hooks.json`; `guard.py`, `stop_gate.py` |
| S-4 | H | **The legacy read-only guard is regex-based and bypassable.** It inspects shell text for `rm`, `mv`, `sed -i`, redirects and a few PowerShell cmdlets. It misses `cp`, `dd`, `rsync`, `install`, `python -c "open(...,'w')"`, `node -e`, `Copy-Item`, `[IO.File]::WriteAllText`, editors, and any script file. Read-only must be a filesystem and audit property, not a pattern match. | `guard.py` `destructive` regex |
| S-5 | H | **Approvals are not bound to a human outside Claude Code.** `state.py approve --by "<name>"` can be run by any process with any name. The only human binding is Claude's permission click, and `EVAL_FORGE_AUTO_APPROVE=1` in the *user's* environment silently removes even that. | `guard.py ask()`; `state.py cmd_approve` |
| S-6 | H | **Evidence has no tamper detection.** `tracker.json`, `history.log`, `forge/gates/*`, `db/verify.json` are "script-owned" by hook convention only. Any `echo >` or any non-Claude operator rewrites them. | `guard.py OWNED`; no hashes or signatures anywhere |
| S-7 | H | **The discovery and transformation method is outsourced to unpinned Claude plugins.** `code-modernization` supplies assess, map, rules, brief, uplift, transform, reimagine, verify and harden. If its commands change, every skill breaks, and nothing in the repository tests that they exist. Non-Claude operators get no method at all. | `plugin.json` dependencies without versions; `discover`, `plan-migration`, `execute`, `migrate` skills |
| S-8 | M | **Parallel waves self-attest.** `execute-wave.js` trusts the build agent's JSON (`status: built`) and asks a merge agent to resolve lockfile conflicts by judgment. The full test suite runs once after all merges, so a breakage cannot be attributed to a ticket. No per-ticket evidence file is written. | `workflows/execute-wave.js` |
| S-9 | M | **Cost accounting is Claude-only and undercounts.** It parses transcripts under the workspace's encoded path; worktree sessions encode a different path, so wave runs are missed. "No transcripts" is reported as unknown, which is right, but there is no per-operator metering at all. | `cost_estimate.py token_spend()` |
| S-10 | M | **Tracker is not concurrency-safe.** One JSON file, no locking; parallel agents are only *told* not to call it. IDs can collide, `history.log` is append-only by convention. | `tracker.py save()` |
| S-11 | M | **An unverified verdict can close tickets.** `jenkins_result.py import` without `--commit` records `commit_verified: false` but still PASS. The tracker rules check `source` and `head`, not `commit_verified`. | `jenkins_result.py`, `skills/tracker/SKILL.md` "Closing a ticket" |
| S-12 | M | **"Done" is self-attested.** The agent ticks `- [x]` boxes in the ticket body, then `tracker.py move done` checks only that no box is unchecked. No link between a box and a verifiable artifact is enforced. | `tracker.py cmd_move` |
| S-13 | M | **Fixtures drifted from the code.** `evals/fixtures/seed_workspace.sh` writes `latest.json` in the old scorecard shape (`overall_score`, `checks`, `scorecard.json`) without `source: "jenkins"` or `head`, which the tracker skill requires. The `gate-refuses-done` eval therefore tests a state the real code never produces. | `seed_workspace.sh` vs `jenkins_result.py cmd_import` |
| S-14 | M | **Windows fragility.** Hooks require bash; `py.sh` probes `python3`/`python`/`py -3`. On this very machine `python` is the Microsoft Store alias and fails; only `py -3` works. A pip entry point would remove the problem. | observed 2026-10-30 |
| S-15 | M | **No schema or transition table for state.** `state.py phase` allows any phase from any phase (only approvals gate it); `state.py set <key>` accepts any key, so a typo (`db-migration`) silently creates a new key and the DB track stays off. | `state.py` |
| S-16 | M | **The README's "honest limits" are enforceable but not enforced.** Weakened tests, suppressions without justification, and schema changes while the DB track is off are forbidden in prose only. All three are detectable in a diff. | `README.md` Honest limits; `remediation-engineer.md` Forbidden list |
| S-17 | L | **Test coverage is thin.** 8 tests cover `jenkins_result.py`, the stop hook and three guard cases. `tracker.py`, `state.py`, `db_verify.py`, `cost_estimate.py` have none. | `tests/` |
| S-18 | L | **No deterministic transformation tooling.** For a *code transformation* product, codemods (OpenRewrite, jscodeshift, ts-morph, Rector, `ng update`, .NET Upgrade Assistant, ast-grep) appear only as notes in `stack-catalog.json`. Every transformation is an LLM edit. | `config/stack-catalog.json` notes |
| S-19 | L | **No characterization-test tooling** although foundation story F1 demands golden outputs for every P0 endpoint; the agent is left to invent a harness each run. | `skills/intake/references/backlog-guide.md` F1 |
| S-20 | L | **Secrets can leak through error text.** `db_verify.py reversibility step()` embeds the last 2,000 characters of a failing command's stderr in `verify.json`; migration tools often echo connection strings. | `db_verify.py cmd_reversibility` |
| S-21 | L | **Install and naming are Claude-specific.** "Plugin", `/plugin marketplace add`, `claude --plugin-dir`. There is no package, no release artifact, no version policy. | `README.md` Install |

### 3.2 In the implied plan ("make it work with any operator and run independently")

| ID | Sev | Shortcoming of the goal as stated | Resolution in this plan |
|----|-----|-----------------------------------|-------------------------|
| P-1 | H | "Any operator" is undefined. Operators differ in hooks, subagents, workflows, permission prompts and headless flags, and the surfaces change monthly (Codex gained hooks in March 2026; Gemini CLI is reportedly being replaced; Cursor CLI hooks fire inconsistently on Windows per user reports). Parity is impossible. | Design for the **lowest common denominator** (Markdown instructions, MCP tools, a CLI) and treat every operator feature as progressive enhancement. Section 5.3 capability matrix, Section 6.6 adapter interface. |
| P-2 | H | "Run independently" is three different things: (a) deterministic parts without any AI, (b) the whole pipeline headless with some AI backend, (c) the gate in CI. Each needs different machinery. | Section 5.1 defines the four run modes and which phase delivers each. |
| P-3 | H | Human checkpoints and headless operation conflict unless approvals have a protocol. | Section 6.4 approval providers; the runner pauses with exit code 3 and resumes when an approval exists. |
| P-4 | M | Building a local gate repeats the 2,850 lines deleted two days ago. Without knowing why they were deleted, the plan might repeat the mistake. | Section 6.7: contract-first, minimal, pluggable checks, one schema shared with Jenkins. Owner decision D-2 in Section 13. |
| P-5 | M | Owning the method means re-authoring content that Anthropic maintains in `code-modernization`. Quality may drop at first. | Section 6.5: own the method, keep external plugins as optional accelerators, vendor Apache-2.0 content with attribution where the owner permits (D-1). |
| P-6 | M | Cost metering differs per operator; a budget gate that says "unknown" blocks headless runs. | Section 6.8: each adapter reports usage from its JSON output; unknown stays FAIL (never silently zero), and the owner chooses per run whether cost is a required check. |
| P-7 | M | A generic agent orchestrator is a bigger product than a migration toolkit. Scope creep risk. | Scope rules: at most three tier-1 adapters in 1.0, no plugin marketplace of our own, no web UI in 1.0 (Section 8, Phase 7 is optional). |
| P-8 | M | Legacy repositories are untrusted input; a standalone runner that reads them is exposed to prompt injection in comments, READMEs and commit messages. | Section 10: policies enforced outside the model, sandboxed headless runs, audit before gate. |
| P-9 | L | Licensing: Trail of Bits skills are CC-BY-SA-4.0 and cannot be vendored into an Apache-2.0 toolkit; `code-modernization` is Apache-2.0 and can, with NOTICE. | Section 7.6 and D-1. |

---

## 4. Guiding principles for the upgrade

1. **Safety in the core, not in the operator.** Anything that must hold (legacy read-only, evidence integrity, human approvals, no weakened checks) is enforced by `forge` itself and verified by `forge audit`. Operator hooks only give earlier, friendlier feedback.
2. **One method, many packagings.** Skills and roles are written once, in operator-neutral vocabulary. Adapters only render and install them.
3. **Deterministic before generative.** Prefer a codemod, a script or a schema check over an LLM edit whenever one exists. The LLM fills the gaps and explains.
4. **Contract-first integration.** The gate, the tracker, the state and the adapter interface each have a versioned JSON schema and a conformance test.
5. **Evidence is written by code, read by models, verified by audit.** Models never write evidence files directly.
6. **Progressive enhancement.** A run on an operator with no hooks and no subagents must still be correct, only slower or with fewer conveniences.
7. **Reuse the existing Python.** Move, do not rewrite, `state`, `tracker`, `jenkins_result`, `db_verify`, `cost_estimate`, `doctor`, `forgelib`. Add tests before moving.
8. **Keep the Claude Code plugin first-class.** It becomes the reference adapter and must stay green every phase.

---

## 5. Target design

### 5.1 Run modes (what "independent" means)

| Mode | Description | Needs an AI? | Needs an operator? | Delivered in |
|------|-------------|--------------|--------------------|--------------|
| **M0 Deterministic** | `forge init/state/tracker/gate import/db/cost/audit/policy` as a CLI and MCP server | No | No | Phase 1, 3 |
| **M1 Operator-driven (interactive)** | A human uses any coding agent; the agent reads the portable skills and calls `forge` via CLI or MCP; the human approves in chat and confirms in a terminal | Yes, the operator's | Yes | Phase 2, 3 |
| **M2 Headless orchestrated** | `forge run --operator <x>` drives the phase machine, spawning operator sessions per phase and per ticket, pausing at checkpoints | Yes | Yes, any with a headless CLI; or the built-in agent in Phase 7 | Phase 4, 5 |
| **M3 CI gate** | `forge gate run` in Jenkins, GitHub Actions or any CI produces the contract artifacts; `forge gate import` records them | No | No | Phase 4 |

### 5.2 Layered architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Operator adapters (thin)                                                     │
│  claude/   codex/   cursor/   copilot/   opencode/   gemini/   generic/       │
│  manifest + hook shim + role rendering + headless driver + usage capture      │
├──────────────────────────────────────────────────────────────────────────────┤
│  Portable method (Agent Skills standard)                                      │
│  skills/ (SKILL.md)   roles/   codemods/ (recipes)   checklists/   templates/ │
│  vocabulary: `forge <cmd>` and `forge.*` MCP tools only                       │
├──────────────────────────────────────────────────────────────────────────────┤
│  forge MCP server (stdio)            forge CLI (pip entry point)              │
├──────────────────────────────────────────────────────────────────────────────┤
│  Core engine (Python package `forge`, stdlib only)                            │
│  state · tracker · evidence ledger · policy · approvals · gate (contract,     │
│  import, reference runner, wait) · db verify · cost ledger · workspace lock   │
│  · runner (phase driver, waves, remediation loop) · adapter interface · audit │
└──────────────────────────────────────────────────────────────────────────────┘
          │ reads/writes                                   │ judged by
          ▼                                                ▼
   <workspace>/forge/  (state, tracker, evidence, gates)   Jenkins / GH Actions / local
```

### 5.3 Operator capability matrix (verified 2026-10-30; re-verify in Phase 0)

| Operator | Instructions file | Skills (SKILL.md standard) | Commands | Subagents | Hooks | MCP | Headless CLI | Human permission prompt | Usage data |
|----------|-------------------|----------------------------|----------|-----------|-------|-----|--------------|-------------------------|------------|
| Claude Code | `CLAUDE.md` | native | skills double as `/name` | `agents/*.md` | `hooks.json` (PreToolUse, Stop, SessionStart, ...) | yes | `claude -p --output-format json`; Claude Agent SDK | yes | JSON output `usage`; transcripts |
| OpenAI Codex CLI | `AGENTS.md` | `.codex/skills` or `.agents/skills` | custom prompts | limited | yes since v0.114 (March 2026); config location (`config.toml [hooks]` vs `hooks.json`) must be verified | `config.toml [mcp_servers]` | `codex exec --json` | approval modes | JSON event stream |
| Cursor (Agent CLI) | `.cursor/rules`, `AGENTS.md` | `.cursor/skills` | `.cursor/commands/*.md` | yes | `hooks.json` (`beforeShellExecution`, `afterFileEdit`, `stop`); CLI firing reported inconsistent on Windows | `.cursor/mcp.json` | `cursor-agent -p` | yes | limited |
| GitHub Copilot CLI | `AGENTS.md`, `.github/copilot-instructions.md` | `.github/skills` | prompt files | `.github/agents/*.agent.md` | `.github/hooks` (verify) | yes | `copilot -p` | yes | limited |
| OpenCode | `AGENTS.md` | `.opencode/skill` | `.opencode/command/*.md` | `.opencode/agent/*.md` | JS plugins (`tool.execute.before`) | `opencode.json` | `opencode run` | yes | JSON output |
| Gemini CLI | `GEMINI.md` | `.gemini/skills` (experimental → default) | TOML commands | experimental | `BeforeTool`/`AfterTool`, exit 2 blocks | yes | `gemini -p` | yes | limited. **Caveat:** a 2026-05 announcement reportedly transitions Gemini CLI to a new CLI; verify before investing |
| Windsurf, Cline, Roo, Amp, Goose, Aider | rules / `AGENTS.md` | varies | varies | varies | mostly none | most yes | varies | varies | none |
| **Generic fallback** | `AGENTS.md` generated by `forge adapt generic` | copied as plain Markdown | none | none | none (post-hoc audit only) | `forge mcp serve` | not applicable | terminal confirmation via `forge approve` | none |

Design consequence: the generic row is the baseline every skill is written for. Hooks, subagents and commands are extras.

Sources consulted for the matrix are listed in Appendix H.

### 5.4 Target repository layout

```
migration-forge/
  pyproject.toml                  package `forge` (stdlib core; extras: db, mcp, dev)
  README.md
  docs/
    plan.md                       this file
    plan-progress.md              per-phase evidence of exit criteria (created in Phase 0)
    adr/                          ADR-001 ... (template in Appendix F)
    operators/<name>.md           per-operator install and known limits
    gate-contract.md              human-readable gate contract
  forge/                          core package
    __init__.py  __main__.py  cli.py
    state.py  tracker.py  evidence.py  policy.py  approvals.py
    gate/  (contract.py, importer.py, runner.py, checks/, wait.py)
    db/    (verify.py, engines.py)
    cost.py  workspace.py  audit.py  doctor.py
    runner/ (driver.py, waves.py, remediation.py, prompts.py)
    adapters/ (base.py, claude.py, codex.py, cursor.py, copilot.py, opencode.py, gemini.py, generic.py, scripted.py)
    mcp/   (server.py, tools.py)
    schemas/ (state.schema.json, tracker.schema.json, backlog.schema.json, gate-summary.schema.json, gate-check.schema.json, verdict.schema.json, ledger.schema.json, adapter-result.schema.json)
  method/                         portable content, no operator words
    skills/<name>/SKILL.md (+ references/, assets/)
    roles/<name>.md
    codemods/<recipe>.yaml
    checklists/*.md
    templates/ (ADR, plan, strategy, ESCALATION)
  adapters/                       packaging per operator (generated parts are built from method/ by `forge adapt`)
    claude/ (.claude-plugin/plugin.json, hooks/hooks.json, skills/ -> rendered, agents/ -> rendered)
    codex/  cursor/  copilot/  opencode/  gemini/  generic/
  gate/
    ci/Jenkinsfile  ci/github-actions.yml  ci/gitlab-ci.yml
    examples/ (summary.json, gate1.json, feedback.md)
  fixtures/legacy-shop/           moved from evals/fixtures
  conformance/                    operator-neutral scenario suite (replaces evals/)
    scenarios/<name>/{scenario.yaml, graders/}
    runner.py
  tests/                          pytest or unittest; unit, contract, integration
  .claude-plugin/marketplace.json  (kept; points at adapters/claude)
```

The current `plugins/migration-forge/` becomes `adapters/claude/` plus generated files. During Phases 1 to 3 the old path keeps working through wrappers (Section 9).

---

## 6. Component designs

### 6.1 Core engine (`forge` package)

- **Packaging:** `pyproject.toml`, console script `forge = forge.cli:main`, `python -m forge` also works. Python floor 3.10 (D-5). Zero runtime dependencies in the base install. Extras: `forge[db]` (psycopg, pymysql, pyodbc), `forge[mcp]` (the `mcp` package), `forge[dev]`.
- **Workspace discovery:** unchanged from `forgelib.workspace()`: nearest ancestor with `forge/state.json`. Add `FORGE_WORKSPACE` environment override for CI.
- **State machine:** explicit transition table (Appendix B). `forge state phase <p>` refuses transitions not in the table unless `--force`, and `--force` is itself an approval-bound action (Section 6.4). `forge state set` accepts only keys declared in `state.schema.json`.
- **Schemas:** every JSON file the core writes has a schema under `forge/schemas/` with a `schema_version` field. Validation is implemented in stdlib (a small validator for the subset of JSON Schema used: type, required, enum, properties, items, additionalProperties). No third-party validator.
- **Tracker:** same model and commands as today, plus file locking (`msvcrt.locking` on Windows, `fcntl.flock` elsewhere) around read-modify-write, monotonic IDs under lock, and ledger entries for every write (6.3). `move <id> done` additionally requires: latest verdict PASS **and** `commit_verified: true` **and** the verdict's `head` contains the ticket's commits (S-11, S-12). Checkbox ticks must carry an `(evidence: <path or build>)` suffix, and `forge tracker move done` verifies each referenced path exists in the ledger.
- **Cost ledger:** `forge/cost/ledger.jsonl`; one entry per adapter invocation `{at, adapter, model, phase, ticket, input, output, cache_read, cache_write, usd?, source: reported|estimated|unknown}`. `forge cost report` sums it. The Claude transcript parser remains as one *source* for interactive Claude sessions, with worktree path encoding fixed (S-9).
- **Doctor:** per-operator checks added (is `claude`/`codex`/`cursor-agent`/`copilot`/`opencode`/`gemini` on PATH, which version, does it support `-p`/`exec --json`).

### 6.2 Policy engine

Single decision point: `forge policy check` reads a JSON event on stdin `{event: pre-tool|pre-commit|pre-gate|audit, tool, input, cwd, actor}` and prints `{decision: allow|deny|ask, reason, rule}`. Exit 0 allow, 2 deny, 3 ask. Every adapter hook shim is a one-liner that pipes the operator's event into this command (Appendix C maps each operator's event shape).

Rules (R-n), each with a unit-test table including bypass attempts:

| Rule | What | Enforcement layers |
|------|------|--------------------|
| R-1 Legacy read-only | no write under `legacy/` or the recorded repo path | (1) `forge workspace lock-legacy` sets read-only permissions on every file (`attrib +R` / `chmod a-w`) and records `legacy_tree_sha` (git tree hash of the legacy ref, or a content hash walk when not git); (2) pre-tool hook deny where hooks exist; (3) `forge audit` recomputes the tree hash before every `gate import` and in CI; mismatch = audit FAIL, gate import refused |
| R-2 Evidence is core-owned | `tracker.json`, `history.log`, `forge/gates/**`, `db/verify.json`, `cost/ledger.jsonl`, `evidence/ledger.jsonl` | ledger hash chain (6.3); audit verifies; hook deny where available |
| R-3 Settings are human-owned | `forge/settings.json` | ledger records the human-made hash at `init`/`forge settings edit --by`; any other change = audit FAIL |
| R-4 Approvals are human-bound | `forge approve` | approval providers (6.4); no environment-variable bypass; conformance mode is a CLI flag recorded in evidence as `actor: conformance` and never produces a PASS that can close tickets |
| R-5 No weakened verification | diff since `base_ref` must not add `skip|xfail|only|it.skip|@Ignore|nosemgrep|NOSONAR|eslint-disable|@ts-ignore|# type: ignore|#nosec` or delete test files/assertions without a `forge-allow: <TICKET> <reason>` marker on the same line | gate check `verification-integrity` in the reference runner and published as a rule in the contract so Jenkins can run it too |
| R-6 No schema change while DB track off | diff contains migration files or DDL (`CREATE|ALTER|DROP TABLE`, migration tool folders) while `db_migration` is false | gate check `db-scope`; execute skill instructs to stop and ask |
| R-7 No production databases | DB URL host matches `prod|production|live` or is not on the allowlist in settings | `forge db` refuses; URL never written to disk; errors redacted (S-20) |
| R-8 Budget | `cost.max_tokens` and per-run USD cap | runner stops spawning adapters when exceeded; gate check `cost` |
| R-9 Secrets | `JENKINS_*`, `FORGE_*_DB_URL` only from environment | core redacts any `scheme://user:pass@` pattern in all output |

### 6.3 Evidence ledger and audit

`forge/evidence/ledger.jsonl`: one line per core write `{at, actor, op, path, sha256, prev}` where `prev` is the sha256 of the previous line (hash chain). `actor` is `core:<command>`, `human:<provider>:<identity>` or `conformance`. `forge audit`:

1. verifies the chain;
2. verifies every core-owned file's current hash equals its last ledger entry;
3. verifies `legacy_tree_sha`;
4. verifies `settings.json` hash;
5. prints a report and exits 0/2.

`forge gate import` runs `forge audit` first and refuses on failure. The runner runs it after every adapter session. CI templates run it before publishing a verdict. This replaces hook-based protection as the thing that guarantees integrity (S-3, S-4, S-6).

Limitation, stated plainly: a ledger in the same filesystem can be rewritten by a determined local process together with every file. The ledger detects accidental and model-driven tampering, not a hostile human with disk access. For stronger guarantees the signed-approval provider and CI-side verification (Section 6.7) hold copies of the chain head.

### 6.4 Approvals

`forge approve <backlog|stack|migration|release|force> --provider <p> [--by <identity>] [--note ...]` with providers:

| Provider | How the human is bound | When to use |
|----------|------------------------|-------------|
| `tty` | the command refuses to run unless stdin is an interactive terminal and the human types the checkpoint name; records OS user | local interactive work, M1 |
| `signed-file` | a human commits `forge/approvals/<checkpoint>.json` with `git commit -S` using a key listed in `settings.approvers`; `forge approve` verifies the signature (`git verify-commit`) | headless M2 with a human reviewer |
| `pr-review` | an approved review on the pull request of the phase branch from a GitHub/GitLab user in `settings.approvers`, read via `gh`/`glab` CLI | teams working through PRs |
| `operator-prompt` | the operator's own permission prompt (Claude Code hook `ask`) **in addition to** `tty`; never alone | Claude adapter convenience |

A model running inside an operator cannot satisfy `tty` (no interactive stdin) or produce a signature. The runner pauses with exit code 3 (`WAITING_APPROVAL`) and a message naming the file or command the human must produce; `forge run --resume` continues once the approval exists and validates.

### 6.5 Portable method (skills, roles, codemods)

Skills keep the Agent Skills format (`SKILL.md` with `name`, `description`, optional `argument-hint`), one folder per skill, references loaded on demand. Rewrite rules for every skill body:

- never mention an operator, a slash command, `${CLAUDE_PLUGIN_ROOT}`, `AskUserQuestion`, the `Skill` tool or a companion plugin by name;
- every action is "run `forge <command>`" or "call the `forge_<tool>` MCP tool", never "edit the file";
- every human checkpoint is "ask the human in chat, then tell them to run `forge approve <x>` (or how to produce the signed approval)";
- every optional accelerator is listed in `method/accelerators.md`, keyed by operator, and referenced as "if the `<name>` accelerator is available on this operator, you may use it for step N; otherwise follow the method below." The method below must be complete on its own.

Skill set for 1.0 (owned, complete):

| Skill | Replaces today | New deterministic helpers |
|-------|----------------|---------------------------|
| `migrate` (orchestrator) | same | reads the transition table from `forge state transitions` |
| `intake` | same | `forge tracker import` validates against `backlog.schema.json` |
| `assess` | `/code-modernization:modernize-preflight/assess/map` | `forge assess scaffold` writes `analysis/<name>/topology.json` skeleton from manifests, routes, SQL files, LOC; the model fills semantics and `ASSESSMENT.md` |
| `extract-rules` | `modernize-extract-rules/review` | `forge rules lint` checks BR ids are unique and each has a source location |
| `plan-stack` | same | unchanged method; sources: endoflife.date, official release pages, the Context7 MCP server if configured (operator-neutral MCP) |
| `plan-migration` | `modernize-brief` + waves | `forge plan waves` computes waves from tracker dependencies and modules deterministically; the model writes the prose |
| `characterize` | nothing today (S-19) | `forge charact record --base-url --cases cases.json` and `replay` produce golden HTTP outputs and a diff report |
| `execute` | `modernize-uplift/transform/reimagine` | `forge codemod run <recipe>` first (6.5.1), then LLM edits; `forge wave run` for parallel waves |
| `gate` | same | `forge gate run|import|wait` |
| `remediate` | same | reads `feedback.md`; the no-progress and cap rules are implemented in `forge runner` for M2 and remain in prose for M1 |
| `verify` | `modernize-verify` | `forge charact replay` against modernized build; writes `VERIFICATION.md` table from results |
| `harden` | `modernize-harden` + `/claude-security` | gate `security` check results; the model proposes patches; no Claude-only scan |
| `status`, `tracker`, `setup` | same | |
| `sql-db-migration`, `cost-assessment` | same (knowledge) | |

Roles (`method/roles/*.md`): `story-analyst`, `stack-researcher`, `codebase-assessor` (new), `rule-extractor` (new), `transformer` (new), `remediation-engineer`, `db-migration-engineer`, `verifier` (new). Each has frontmatter `{name, purpose, inputs, outputs, tools_needed: [read, write, shell, web], model_tier: strong|standard|cheap}`. Adapters render them into the operator's agent format where one exists, or inline them into the session prompt where none does.

#### 6.5.1 Codemod recipes

`method/codemods/<recipe>.yaml`:

```yaml
name: express-to-typescript
applies_to: {backend: express-js}
tool: {name: ts-migrate, check: "npx ts-migrate --version", install_hint: "npm i -D ts-migrate"}
steps:
  - run: "npx ts-migrate-full {root}"
expects: ["tsconfig.json", "**/*.ts"]
after: "run the project tests; fix type errors by hand only where the tool left `@ts-expect-error` markers"
```

Initial recipe set (install checks only, tools are not vendored): OpenRewrite (Spring Boot 2→3, javax→jakarta), `ng update`, jscodeshift React class→hooks, ts-morph template, Rector (PHP), .NET Upgrade Assistant, ast-grep rules runner, `pgloader`/`ora2pg` for DB assessment. `forge codemod list` shows which are usable on this machine.

### 6.6 Operator adapters

Python interface (`forge/adapters/base.py`):

```python
class Adapter(Protocol):
    name: str
    def capabilities(self) -> Capabilities: ...          # hooks, subagents, commands, headless, usage
    def detect(self) -> DetectResult: ...                 # on PATH? version? headless flag works?
    def install(self, workspace: Path, scope: Literal["project","user"]) -> list[Path]: ...
    def render_roles(self, roles: list[Role]) -> list[Path]: ...
    def invoke(self, req: InvokeRequest) -> InvokeResult: ...
        # req: prompt, cwd, allowed_tools, max_turns, budget_tokens, timeout_s, env
        # result: text, exit_code, usage (or None), transcript_path, duration_s
    def hook_shim(self) -> Optional[HookShim]: ...        # files to write so operator hooks call `forge policy check`
```

Adapters in 1.0: `claude` (headless via `claude -p --output-format json --max-turns --allowedTools`, or the Claude Agent SDK where installed; models `claude-opus-5-5` for strong roles, `claude-sonnet-5-5` standard, `claude-haiku-5-5` cheap), `codex` (`codex exec --json`), `generic` (install only, no `invoke`), `scripted` (replays canned responses for tests). Phase 5 adds `cursor`, `copilot`, `opencode`, and `gemini` only if its product status is confirmed.

Each adapter has a **contract test**: given a fake operator binary (a shell script in `tests/fakes/`) that emits the operator's real JSON shapes, `invoke()` returns the normalized result and usage. Real-operator runs happen only in the conformance suite.

### 6.7 Gate: contract, reference runner, CI templates

**Contract** (`forge/schemas/gate-summary.schema.json`, `gate-check.schema.json`, `docs/gate-contract.md`), derived from what `jenkins_result.py` accepts today so existing pipelines keep working:

```jsonc
// results/<phase>/summary.json
{ "schema_version": "1", "phase": "after", "enforced": true, "all_passed": false,
  "failed_gates": ["gate1"], "complete": true, "skipped_checks": {},
  "gates": { "gate1": {"passed": false, "title": "Static analysis & security"}, "gate2": {...} },
  "commit": "<sha built>", "build": "<id or url>", "tool_versions": {...} }
// results/<phase>/gate1.json
{ "title": "...", "checks": [ {"metric": "semgrep_high", "value": 2, "rule": {"max": 0}, "passed": false, "missing": false} ] }
// results/<phase>/feedback.md : per gate, `file:line - rule - message` findings
```

New fields (`schema_version`, `commit`, `tool_versions`) are optional for importers; `forge gate import` uses `commit` when `--commit` is absent and marks `commit_verified` accordingly.

**Reference runner** `forge gate run --root <modernized> --out results/after [--checks a,b,c] [--baseline]`: a registry of checks, each a small module producing one `gateN.json` entry and feedback lines. 1.0 checks: `tests` (configured command, exit code, junit if present), `coverage` (lcov/cobertura/jacoco/coverage.py parsing), `lint`/`typecheck` (configured commands), `secrets` (gitleaks if installed), `sast` (semgrep if installed), `deps` (osv-scanner or `npm audit`/`pip-audit` if installed), `pii` (own stdlib scanner, ported from the deleted `pii_scan.py` after review), `verification-integrity` (R-5), `db-scope` (R-6), `db-parity` (reads `db/verify.json`), `behavior` (HTTP expectation cases, ported from the deleted `expect.py` after review), `cost` (R-8). A required check whose tool is missing **fails** with `missing: true`, never passes silently. Thresholds come from `forge/gate.json` in the workspace (human-owned, ledgered like settings), with the same `rule: {max|min}` shape as the contract.

**Judge choice per run:** `settings.gate.judge = jenkins | ci-artifact | local`. `jenkins` and `ci-artifact` use `forge gate wait --url <summary.json url> --commit <sha> --timeout` to poll and then import; `local` runs the reference runner and imports its output. The README's position that thresholds belong to the pipeline owners is preserved for `jenkins`.

**CI templates** in `gate/ci/`: a Jenkinsfile and a GitHub Actions workflow that install `forge`, run `forge audit`, run `forge gate run` (or the team's own scanners that write the contract), and archive `results/`.

### 6.8 Headless runner

`forge run --operator <adapter> [--until <phase>] [--sandbox docker|none] [--budget-tokens N] [--max-remediation N]`:

1. loads state, computes the next transition from the table;
2. builds the session prompt from the skill for that phase, the role prompts it needs, and a context digest (`forge context digest`: state, board, latest verdict, plan excerpt, no raw legacy source);
3. invokes the adapter with `allowed_tools` restricted to what the phase needs and `cwd` = workspace (in `docker` sandbox: image with the toolchain, workspace mounted read-write, `legacy/` mounted read-only, network limited to an allowlist);
4. records usage in the cost ledger, runs `forge audit`, validates the artifacts the phase must produce (`forge phase verify <phase>`: files exist, schemas validate, tracker validates);
5. at a checkpoint, exits 3 and prints how to approve; `--resume` continues;
6. for `execute` waves: `forge wave run` creates one git worktree per ticket, invokes one adapter session per ticket in parallel up to `--parallel`, runs the ticket's acceptance tests in the worktree itself (not self-reported), merges sequentially with the full test suite **after each merge** so failures are attributable, writes `forge/evidence/waves/<n>/<ticket>.json`, and never touches the tracker from inside a worktree (S-8);
7. for `gate`/`remediate`: implements the loop that `stop_gate.py` enforced by prose: import verdict → if FAIL and budget remains → remediate session → commit → gate wait → repeat; no-progress rule (two identical failure sets) and cap → `escalated` with `forge/ESCALATION.md` (S-3 for M2).

Exit codes: 0 done or phase complete, 2 failure, 3 waiting for approval, 4 waiting for an external gate, 5 escalated, 6 budget exhausted.

### 6.9 MCP server

`forge mcp serve` (stdio; `forge[mcp]` extra). Tools are 1:1 with CLI subcommands that are safe for a model to call: `forge_state_show`, `forge_state_phase`, `forge_state_set`, `forge_tracker_*` (board, next, show, list, add, link, set, move, validate, import, export), `forge_gate_import`, `forge_gate_show`, `forge_gate_run`, `forge_db_compare`, `forge_db_reversibility`, `forge_cost_report`, `forge_policy_check`, `forge_audit`, `forge_plan_waves`, `forge_codemod_list`, `forge_codemod_run`, `forge_charact_*`. **Not exposed:** `approve`, `settings edit`, anything with `--force`. Resources: `forge://board`, `forge://plan`, `forge://verdict/latest`, `forge://skill/<name>`, `forge://role/<name>`. Every tool result includes the ledger head hash so the model can cite it.

### 6.10 Conformance suite (replaces `evals/`)

`conformance/scenarios/<name>/scenario.yaml`: `{workspace_fixture, phase, prompt, allowed_tools, max_turns, graders: [{type: file_exists|regex_trace|forbidden_command|json_path|llm, ...}]}`. `conformance/runner.py` runs a scenario through any adapter's `invoke()`, collects the transcript, applies deterministic graders, and uses an LLM grader only where the scenario says so (through the same adapter, so no second provider is needed). The five existing eval cases are ported first, with the fixture fixed (S-13). The suite runs nightly against real operators and on every PR with the `scripted` adapter.

---

## 7. Cross-cutting decisions

### 7.1 Naming and packaging
Product name stays **Migration Forge**; the artifact is a Python package `migration-forge` exposing `forge`. The word "plugin" is reserved for per-operator packagings. Distribution: PyPI (or an internal index), `pipx install migration-forge`, and a zipapp (`forge.pyz`) for machines without pip. Releases are tagged `vX.Y.Z`; the Claude plugin manifest version tracks the package version.

### 7.2 Compatibility window
`plugins/migration-forge/scripts/*.py` become thin wrappers (`from forge.cli import main`) in Phase 1 and are deleted in Phase 6. Slash command names are unchanged. `forge/state.json` from 0.1 is migrated by `forge upgrade-workspace` (adds `schema_version`, ledger bootstrap with current hashes marked `actor: migration`).

### 7.3 Python and OS support
Python 3.10 to 3.13 tested in CI on Windows, Linux and macOS (D-5). No bash requirement outside the Claude adapter's `hooks.json`, which calls `python -m forge.policy` through a tiny cross-platform launcher that tries `py -3`, `python3`, `python` in that order (the current `py.sh` logic, kept only there).

### 7.4 Testing standards
Unit coverage for `forge/` at or above 80 percent lines (measured with `coverage.py` in CI); every policy rule has a table test including at least five bypass attempts; every adapter has a contract test with a fake binary; the `scripted` adapter runs the legacy-shop fixture end to end in CI on every PR; schemas have positive and negative fixture files.

### 7.5 Documentation standards
Each operator gets `docs/operators/<name>.md`: install, how skills are discovered, how hooks are wired (or that they are not), how to run headless, known limits, verification date. `docs/gate-contract.md` is the single page a pipeline team needs.

### 7.6 Licensing and dependencies
- Core: stdlib only. Extras: `mcp` (MIT), `psycopg`/`pymysql`/`pyodbc` (LGPL/MIT/MIT) only in `forge[db]`.
- Content: `code-modernization` is Apache-2.0; vendoring the *method text* with a NOTICE entry is permitted, subject to D-1. Trail of Bits skills (CC-BY-SA-4.0) are never vendored; they stay optional accelerators. `superpowers` and `mattpocock-skills` (MIT) stay optional accelerators.
- Scanners (semgrep, gitleaks, trivy, osv-scanner, squawk, infracost) are invoked if installed, never vendored.

---

## 8. Phased delivery plan

Effort is for one experienced engineer with an AI coding agent; a second engineer can roughly halve the calendar time of Phases 2, 4 and 5. Every phase ends with the exit criteria recorded in `docs/plan-progress.md`.

### Phase 0: Foundations and decisions (1 week)

Goal: remove unknowns before moving code.

| Task | Deliverable | Acceptance criteria |
|------|-------------|---------------------|
| 0.1 Decisions | `docs/adr/ADR-001` to `ADR-006` answering D-1 to D-6 (Section 13), each with the owner's approval line | all six ADRs have status Accepted |
| 0.2 Gate contract extraction | `forge/schemas/gate-summary.schema.json`, `gate-check.schema.json`, `docs/gate-contract.md`, `gate/examples/*` | `tests/test_contract.py` validates the examples and the fixtures the current tests use; the current `jenkins_result.py` imports every example unchanged |
| 0.3 Operator verification spike | `docs/operators/<name>.md` for Claude Code, Codex, Cursor, Copilot, OpenCode, Gemini (or successor) with: install path for skills, hook mechanism and event shape, headless command and JSON output sample, verification date | each file has a captured real JSON output sample from a headless run of `echo` level prompt; Gemini status decided (keep or drop) |
| 0.4 Repository CI | GitHub Actions (or Jenkins) running unit tests on Windows + Linux + macOS, Python 3.10 and 3.13 | green on `main` |
| 0.5 Fixture fix (S-13) | `seed_workspace.sh` writes the verdict shape `jenkins_result.py` produces | gate-refuses-done scenario passes with the real shape |
| 0.6 Progress log | `docs/plan-progress.md` created with the Phase 0 table filled | file exists, reviewed by owner |

Exit: all criteria met; ADRs accepted.

### Phase 1: Core extraction and hardening (2 to 3 weeks)

Goal: `pip install -e .` gives a `forge` CLI that does everything the scripts do, safely, with tests; the Claude plugin still works through wrappers.

| Task | Deliverable | Acceptance criteria |
|------|-------------|---------------------|
| 1.1 Package skeleton | `pyproject.toml`, `forge/cli.py` with subcommand routing, `python -m forge` | `forge --help` lists all subcommands on all three OS in CI |
| 1.2 Move and test `state` | `forge/state.py` with transition table (Appendix B), key whitelist, `schema_version` | tests: every allowed transition, every refused one, typo key refused; `forge state transitions` prints the table |
| 1.3 Move and test `tracker` | `forge/tracker.py` with locking, ledgered writes, evidence-suffix check on ticks, `commit_verified` requirement | tests: concurrent `add` from 8 processes yields unique IDs; `move done` refused without evidence suffix / with `commit_verified: false` |
| 1.4 Evidence ledger + audit | `forge/evidence.py`, `forge/audit.py`, `forge audit` | tests: chain verifies; a hand edit of `tracker.json` is detected; a legacy file change is detected via tree hash |
| 1.5 Workspace lock | `forge workspace lock-legacy|verify-legacy` | tests on Windows and POSIX: write to a locked file fails; `verify-legacy` detects a change |
| 1.6 Policy engine | `forge/policy.py`, `forge policy check` | table tests for R-1 to R-9 with at least 5 bypass attempts each (`cp`, `dd`, `python -c`, `Copy-Item`, `[IO.File]`, `tee`, `rsync`, heredoc) |
| 1.7 Approvals | `forge/approvals.py` with `tty`, `signed-file`, `pr-review` providers; `EVAL_FORGE_AUTO_APPROVE` removed | tests: non-tty stdin refused; unsigned approval file refused; signed by a listed key accepted (test key generated in CI) |
| 1.8 Gate import move | `forge/gate/importer.py`, `forge gate import|show` | the 8 existing tests pass against the new module; import refuses when `forge audit` fails |
| 1.9 DB verify move | `forge/db/verify.py`; redaction of URLs in all error paths (S-20) | tests with sqlite for compare/reversibility/snapshot; error text never contains `://user:` |
| 1.10 Cost ledger | `forge/cost.py`, `forge cost report`; Claude transcript source with worktree encoding fix | tests: ledger sums; worktree path encoding found |
| 1.11 Doctor | `forge doctor` with operator detection | runs on all three OS |
| 1.12 Compatibility wrappers | `plugins/migration-forge/scripts/*.py` import from `forge`; `hooks.json` shims call `forge policy check`; `upgrade-workspace` | `claude plugin validate` passes; the five eval cases pass with a real Claude run (manual, recorded) |
| 1.13 Coverage | coverage report in CI | `forge/` at or above 80 percent lines |

Exit: Claude plugin green through wrappers; `forge` CLI covers S-3 (for M0), S-4, S-5, S-6, S-9 partially, S-10, S-11, S-12, S-14, S-15, S-17, S-20.

### Phase 2: Portable method (2 to 3 weeks)

Goal: the skills, roles and recipes are complete and operator-neutral; the Claude adapter renders them.

| Task | Deliverable | Acceptance criteria |
|------|-------------|---------------------|
| 2.1 Vocabulary lint | `tests/test_method_lint.py` | fails on any operator word, slash command, `${CLAUDE_PLUGIN_ROOT}`, `AskUserQuestion`, `Skill` in `method/` |
| 2.2 Rewrite existing 11 skills | `method/skills/*` | lint passes; each skill's steps reference only `forge` commands or MCP tools; `method/accelerators.md` lists the optional plugins per operator |
| 2.3 New skills: `assess`, `extract-rules`, `characterize`, `verify`, `harden` | `method/skills/*` + helpers `forge assess scaffold`, `forge rules lint`, `forge charact record|replay`, `forge plan waves` | helpers have unit tests; `forge charact` records and replays the legacy-shop fixture's three endpoints and reports a diff when a response changes |
| 2.4 Roles | `method/roles/*.md` (8 roles) with frontmatter | schema-validated; the Claude adapter renders them to `agents/*.md` identical in behaviour to today's four |
| 2.5 Codemod recipes | `method/codemods/*.yaml`, `forge codemod list|run` | recipe schema validated; `list` shows install status; `run` executes a recipe against a fixture with a fake tool in CI |
| 2.6 Checklists and templates | moved to `method/` | referenced paths updated; tracker init copies them |
| 2.7 Claude adapter rendering | `forge adapt claude` generates `adapters/claude/skills|agents` from `method/` | generated output is committed; a diff test fails if someone edits generated files by hand |
| 2.8 Method review | owner review of the new `assess`/`extract-rules`/`verify`/`harden` content against the `code-modernization` originals (D-1) | review notes in `docs/plan-progress.md` |

Exit: a Claude Code run of the legacy-shop fixture through intake → discover → plan-stack with the new skills (manual, recorded), no reference to the external plugins required.

### Phase 3: MCP server and generic adapter (1 to 2 weeks)

Goal: any MCP-capable operator can run the method in M1.

| Task | Deliverable | Acceptance criteria |
|------|-------------|---------------------|
| 3.1 MCP server | `forge mcp serve` with the tool list in 6.9 and resources | `tests/test_mcp.py` drives it with an MCP client over stdio: list tools, call `forge_tracker_board`, read `forge://board`; `approve` is absent |
| 3.2 Generic adapter | `forge adapt generic` writes `AGENTS.md` (method index + rules), copies skills to `.agents/skills/`, writes an MCP config snippet | files generated for the fixture; `AGENTS.md` lint-clean |
| 3.3 Manual M1 runs | run intake on the legacy-shop fixture with two non-Claude operators (recommend Codex and OpenCode) via MCP | transcripts saved under `conformance/results/`; backlog created via `forge_tracker_import`; no hand edits of evidence detected by `forge audit` |
| 3.4 Docs | `docs/operators/generic.md` | reviewed |

Exit: M0 and M1 delivered.

### Phase 4: Headless runner and local gate (3 weeks)

Goal: `forge run` drives the whole pipeline with the Claude and Codex adapters; a run can be gated locally or by CI.

| Task | Deliverable | Acceptance criteria |
|------|-------------|---------------------|
| 4.1 Adapter interface + `scripted` adapter | `forge/adapters/base.py`, `scripted.py` | contract tests |
| 4.2 Claude adapter `invoke` | `claude -p` JSON parsing, usage capture, allowed tools, max turns | contract test with fake binary; one real recorded run |
| 4.3 Codex adapter `invoke` | `codex exec --json` parsing | same |
| 4.4 Phase driver | `forge run`, `forge phase verify`, `forge context digest`, exit codes | integration test: `scripted` adapter completes intake → plan-migration on the fixture with approvals provided by `signed-file` in CI |
| 4.5 Waves | `forge wave run` | integration test: two tickets in worktrees, acceptance tests run by the core, per-merge test run, evidence files written; a deliberately failing ticket is reported `failed`, not `merged` |
| 4.6 Remediation loop | `forge/runner/remediation.py` | integration test: FAIL → remediate → PASS with the `scripted` adapter; no-progress rule escalates |
| 4.7 Gate reference runner | `forge gate run` with the 1.0 check registry; `forge/gate.json` thresholds | each check has a unit test with a fixture; a missing required tool fails with `missing: true`; output validates against the contract; `forge gate import` of its own output works |
| 4.8 `forge gate wait` | polling with auth from env, timeout | test against the local HTTP server used by the existing tests |
| 4.9 CI templates | `gate/ci/Jenkinsfile`, `github-actions.yml` | the GitHub Actions template runs against the fixture in this repository's CI and produces a PASS artifact |
| 4.10 Sandbox | `--sandbox docker` with read-only legacy mount and network allowlist | integration test skipped when Docker is absent, run in CI on Linux |
| 4.11 Cost | adapter usage into the ledger; `cost` check | ledger entries for every invoke in the integration tests; `source: unknown` makes the cost check fail when required |

Exit: M2 with Claude and Codex, M3 with the reference runner; S-1, S-2, S-7 (method owned), S-8, S-9, S-16, S-18, S-19 closed.

### Phase 5: More adapters and the conformance suite (2 weeks)

| Task | Deliverable | Acceptance criteria |
|------|-------------|---------------------|
| 5.1 Cursor, Copilot, OpenCode adapters (Gemini per ADR) | `forge/adapters/*.py`, `forge adapt <name>`, hook shims where the operator has hooks | contract tests; one real recorded run each |
| 5.2 Conformance suite | `conformance/runner.py`, the five ported scenarios plus: `legacy-locked-no-hooks` (generic adapter, write attempt, audit catches it), `approval-not-fakeable`, `wave-attribution`, `weakened-test-detected`, `schema-change-db-off` | all scenarios pass with `scripted`; nightly job runs them with real operators and publishes a matrix |
| 5.3 Operator docs | `docs/operators/*.md` complete | reviewed |

Exit: at least three real operators pass the conformance suite's deterministic graders.

### Phase 6: Hardening, docs, release 1.0 (1 to 2 weeks)

| Task | Deliverable | Acceptance criteria |
|------|-------------|---------------------|
| 6.1 Security review | review against Section 10; `docs/security.md` | findings fixed or accepted with an owner |
| 6.2 Remove compatibility wrappers | delete `plugins/migration-forge/scripts/*.py` duplicates; `adapters/claude` is the plugin | `claude plugin validate` passes on `adapters/claude` |
| 6.3 README and migration guide | new `README.md`, `docs/migrating-from-0.1.md` | reviewed |
| 6.4 Release | tag `v1.0.0`, PyPI/internal publish, zipapp, marketplace manifest updated | `pipx install migration-forge` and `/plugin install` both work from a clean machine (recorded) |

### Phase 7 (optional, after 1.0): built-in agent and approval UI

Only if the owner decides (D-7): a `builtin` adapter that runs its own tool loop against the Anthropic API (default model `claude-opus-5-5`) and against an OpenAI-compatible endpoint, with tools limited to the `forge` MCP server plus sandboxed file and shell tools; and a small local web page for approvals backed by the `signed-file` provider. Not part of the 1.0 commitment.

---

## 9. Migration and compatibility strategy

1. Phase 1 introduces the package next to the plugin; wrappers keep every current command working.
2. Phase 2 moves content to `method/`; the Claude plugin's `skills/` and `agents/` become generated files.
3. Phase 3 lets other operators use the method through MCP without any change to the Claude path.
4. Phase 6 deletes wrappers and moves the plugin to `adapters/claude/`. The marketplace `source` path changes once; users reinstall.
5. Existing workspaces: `forge upgrade-workspace` adds `schema_version`, bootstraps the ledger with current hashes (`actor: migration`), records `legacy_tree_sha`, and leaves everything else untouched. The next `forge audit` starts from that baseline.

---

## 10. Security and safety design

- **Untrusted input:** the legacy repository, its commit history, its READMEs and comments are data. Skills tell the model so, the context digest never includes raw legacy text, and no decision that matters (approvals, evidence, verdicts) can be made by the model.
- **Legacy read-only:** filesystem lock plus tree-hash audit (R-1). Hooks are a convenience.
- **Evidence integrity:** hash-chained ledger, audit before gate import and in CI (R-2, R-3).
- **Approvals:** identity-bound providers; no environment bypass; conformance mode is explicit and cannot close tickets (R-4).
- **Secrets:** environment only; global redaction of credential-bearing URLs in all output and files (R-7, R-9).
- **Sandbox for headless runs:** Docker with read-only legacy mount, no network except an allowlist (package registries, endoflife.date, the gate URL), resource limits.
- **No weakening:** `verification-integrity` and `db-scope` gate checks (R-5, R-6).
- **Supply chain:** scanners are invoked by PATH, never downloaded by `forge`; versions recorded in `tool_versions`.
- **Least privilege for the model:** `allowed_tools` per phase in the runner; MCP server exposes no approval or force operations.

---

## 11. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Operator surfaces change during the project (hooks location, CLI flags, product renames) | high | medium | adapters are thin; `detect()` probes at runtime; conformance nightly catches drift; Phase 0 spike dates every fact |
| Hooks fire unreliably (reported for Cursor CLI on Windows) | medium | low | safety never depends on hooks (Section 4 principle 1) |
| Re-authored method is weaker than `code-modernization` at first | medium | medium | D-1 vendoring with attribution; accelerators stay usable on Claude Code; owner review task 2.8 |
| Local gate grows into the deleted 2,850-line monolith again | medium | medium | contract-first, check registry with one module per check, each with a fixture test; scope list is fixed in 6.7; anything else needs an ADR |
| Budget checks block headless runs because usage is unknown on some operators | medium | medium | per-adapter usage parsing; `cost` is required only when the owner sets it; unknown is never reported as zero |
| Windows path and permission edge cases (OneDrive, junctions, `attrib`) | high | medium | CI on Windows from Phase 0; lock tests on both OS; junction handling tested explicitly |
| Approval friction slows teams | medium | low | three providers; `tty` for local work takes seconds |
| Organizational dependency on the pipeline team adopting the contract | medium | high | the contract is backward compatible with what the pipeline already produces; `local` judge works without them |
| Scope creep toward a general agent framework | high | high | Section 0 rules; Phase 7 optional; three tier-1 adapters |
| Cost of real-operator conformance runs | medium | low | nightly only; PRs use the `scripted` adapter |

---

## 12. Critique of this plan

This section records the critical review of the plan itself: first the author's own critique, then findings from an independent review performed by a second reviewer who read the repository and this document without the author's conclusions, and what changed as a result.

### 12.1 Author's critique

1. **It is a rewrite wearing a refactor's clothes.** Roughly 70 percent of the Python moves, but the skills are rewritten, the workflow is replaced, the hooks are demoted, and the gate runner is rebuilt. Calling it 12 to 16 weeks assumes an experienced engineer with an AI agent and no organizational waiting time; a part-time owner should expect double. Mitigation: phase gates and the rule that the Claude plugin stays green make partial delivery useful (Phase 1 alone fixes seven H/M shortcomings).
2. **The local gate was deleted two days ago and the plan brings it back.** The plan assumes the deletion was about scope and maintenance, not principle, because the README still calls the gates "the thing the pipeline must pass" rather than "unwanted". If the owner's reason was "the plugin must never judge itself", then `local` judge mode should be dropped and M2 runs would always need CI. This is decision D-2 and the plan should not proceed past Phase 0 without it.
3. **Approvals-by-signature is unusual for application teams.** Many teams have no signing keys. The `pr-review` provider covers them, but it requires `gh`/`glab` and a PR-based flow. The `tty` provider is the practical default and it only proves "a human at a terminal", not "an authorized human". The plan accepts this and says so; it does not claim non-repudiation.
4. **The evidence ledger is not tamper-proof against a local human.** Section 6.3 states this. It stops models and accidents. Stronger guarantees need the CI side to keep the chain head, which Phase 4's templates do, but only when a CI exists.
5. **"Own the method" is a content problem, not a code problem.** Writing an `assess` skill that matches a maintained upstream plugin takes domain time that engineers underestimate. Task 2.8 exists for this reason; the owner should expect iteration after 1.0.
6. **The codemod layer is shallow in 1.0.** Recipes are wrappers with install checks, not vendored tools. That is deliberate (licensing, size), but it means "deterministic before generative" is only as good as the tools installed on the machine.
7. **The matrix will be stale on the day it ships.** Every row carries a verification date for that reason, and the nightly conformance job is the real source of truth.
8. **Testing with the `scripted` adapter can give false confidence.** It proves the runner's control flow, not that a real model follows the skills. Only the nightly suite proves that, and it costs tokens.
9. **The plan asks a lot of the owner up front** (seven decisions). This is intentional: each one changes the shape of Phases 1 to 4, and guessing would waste more than asking.

### 12.2 Independent review findings and resolutions

_Filled in below after the independent review; each finding states whether it was accepted, and what changed in the plan._

### 12.3 What this plan deliberately does not do

- No web UI, no hosted service, no plugin marketplace of our own.
- No vendoring of scanners or codemod tools.
- No attempt at feature parity across operators; only correctness parity.
- No support for operators without MCP *and* without a way to run shell commands; the method needs `forge`.
- No automatic approval under any circumstance.

---

## 13. Decisions the owner must make (before Phase 1)

| ID | Decision | Options | Recommendation |
|----|----------|---------|----------------|
| D-1 | Method ownership vs `code-modernization` | (a) re-author from scratch; (b) vendor the Apache-2.0 method text with NOTICE and adapt; (c) keep it as a hard dependency (Claude-only) | **(b)**: fastest path to an owned, complete method; keep upstream as an accelerator on Claude Code |
| D-2 | Who judges | (a) Jenkins only (no local runner, M2 always needs CI); (b) local reference runner **and** CI with one contract; (c) local only | **(b)** |
| D-3 | Tier-1 operators for 1.0 | any three of Claude Code, Codex, Cursor, Copilot, OpenCode; Gemini depends on its product status | **Claude Code, Codex, generic MCP** in Phase 4; Cursor/Copilot/OpenCode in Phase 5 |
| D-4 | Approval providers accepted in the organization | `tty`, `signed-file`, `pr-review` | all three, `tty` default locally, `pr-review` in headless team runs |
| D-5 | Python floor and distribution | 3.9 or 3.10; PyPI or internal index; zipapp yes/no | **3.10**, internal index first, zipapp yes |
| D-6 | Gate check set for 1.0 and whether `cost` is required by default | the 6.7 list; cost required or optional | the 6.7 list; `cost` optional by default, required when `max_tokens` is set |
| D-7 | Phase 7 built-in agent | go / no-go after 1.0 | decide after Phase 5 with real conformance data |

---

## 14. Success criteria for 1.0

1. A user with only `pipx` and git can `forge init`, lock legacy, import a Jenkins verdict, and audit a workspace with no AI installed (M0).
2. A user of any MCP-capable coding agent can run intake through plan-migration on the legacy-shop fixture using only the portable skills and the `forge` MCP server, and `forge audit` passes afterwards (M1).
3. `forge run --operator claude` and `forge run --operator codex` complete the fixture from intake to a PASS verdict with `judge=local`, pausing for approvals at the four checkpoints (M2).
4. The GitHub Actions template produces a contract-conformant verdict that `forge gate import` accepts (M3).
5. Every S-n item marked H or M in Section 3.1 is closed or has an accepted ADR explaining why not.
6. The conformance suite's deterministic graders pass for at least three real operators.

---

## Appendix A: `forge` CLI specification (1.0)

```
forge init --name <n> --repo <path> --story <file|text> [--target <hint>] [--with-db]
forge upgrade-workspace
forge status | forge doctor [--operators]
forge state show | transitions | phase <p> [--force] | set <key> <json>
forge approve <backlog|stack|migration|release|force> --provider <tty|signed-file|pr-review> [--by <id>] [--note <text>]
forge settings edit --by <id>                       # records the human-made hash
forge tracker init|import|add|move|set|link|list|next|show|validate|board|export-jira   (as today)
forge workspace lock-legacy | verify-legacy
forge audit [--json]
forge policy check  (JSON event on stdin)           # exit 0 allow, 2 deny, 3 ask
forge gate run --root <dir> --out <dir> [--checks a,b] [--baseline]
forge gate import [<summary.json path|url>] [--commit <sha>] [--build <id>]
forge gate show | forge gate wait --url <u> --commit <sha> [--timeout <s>]
forge db compare|reversibility|snapshot             (as today, URL redaction)
forge cost report [--out <file>]
forge assess scaffold --name <n> | forge rules lint | forge plan waves
forge charact record --base-url <u> --cases <file> --out <dir> | replay --base-url <u> --golden <dir>
forge codemod list | run <recipe> [--root <dir>]
forge context digest [--phase <p>]
forge run --operator <name> [--until <phase>] [--resume] [--sandbox docker|none] [--budget-tokens N] [--max-remediation N] [--parallel K]
forge wave run --wave <n> --operator <name> [--parallel K]
forge phase verify <phase>
forge adapt <claude|codex|cursor|copilot|opencode|gemini|generic> [--scope project|user]
forge mcp serve
forge conformance run [--operator <name>] [--scenario <name>]
```

Exit codes: 0 ok · 2 refused/failed · 3 waiting for approval · 4 waiting for external gate · 5 escalated · 6 budget exhausted.

## Appendix B: State transition table

| From | To | Requires approval(s) | Notes |
|------|----|----------------------|-------|
| (none) | intake | | `forge init` |
| intake | discover | backlog | |
| discover | plan-stack | | |
| plan-stack | plan-migration | backlog, stack | |
| plan-migration | execute | backlog, stack, migration | |
| execute | gate | | |
| gate | remediate | | on FAIL |
| gate | verify | | on PASS, when all tickets of the plan are done |
| gate | execute | | on PASS, more tickets remain |
| remediate | gate | | |
| remediate | escalated | | cap or no-progress |
| verify | gate | | |
| verify | harden | | gate PASS after verify |
| harden | gate | | |
| harden | done | release | gate PASS after harden |
| escalated | remediate, execute, plan-migration | per target | only via `forge state phase --force` with the `force` approval |
| any | escalated | | always allowed |

## Appendix C: Hook shim mapping

| Operator | Event | Shim command | Mapping to `forge policy check` |
|----------|-------|--------------|--------------------------------|
| Claude Code | `PreToolUse` (Write, Edit, MultiEdit, NotebookEdit, Bash, PowerShell) | `python -m forge.policy claude` | `tool_name` → `tool`, `tool_input` → `input`; deny → exit 2 with stderr; ask → `permissionDecision: ask` |
| Claude Code | `Stop` | `python -m forge.policy claude-stop` | kept for M1 convenience; M2 uses the runner loop |
| Codex CLI | `PreToolUse` (verify config location in Phase 0) | `forge policy check --format codex` | same |
| Cursor | `beforeShellExecution`, `afterFileEdit` (post-hoc) | `forge policy check --format cursor` | `afterFileEdit` cannot block; it triggers `forge audit` and reports |
| Gemini CLI | `BeforeTool` | `forge policy check --format gemini` | exit 2 blocks |
| OpenCode | plugin `tool.execute.before` | JS shim spawning `forge policy check` | throw to block |
| Copilot CLI | `.github/hooks` (verify) | `forge policy check --format copilot` | |
| generic | none | none | `forge audit` after the session and before gate import |

## Appendix D: Evidence ledger line

```json
{"at":"2026-10-30T10:00:00+00:00","actor":"core:tracker.move","op":"write","path":"forge/tracker/tracker.json",
 "sha256":"<hex>","prev":"<sha256 of previous line>","note":"STORY-001 review->done"}
```

## Appendix E: Adapter result schema

```json
{"adapter":"codex","model":"<id or null>","exit_code":0,"text":"...","usage":{"input":1200,"output":300,"cache_read":0,"cache_write":0,"source":"reported"},
 "transcript_path":"forge/evidence/sessions/2026-10-30T10-00-00-intake.jsonl","duration_s":84.2}
```

## Appendix F: ADR template

```markdown
# ADR-NNN: <title>
Status: Proposed | Accepted | Superseded by ADR-MMM     Date: YYYY-MM-DD
Deciders: <owner name>
## Context
## Decision
## Consequences
## Plan sections changed
## Approval
Approved by <name> on <date>.
```

## Appendix G: Glossary

- **Operator:** a coding agent product (Claude Code, Codex CLI, Cursor, Copilot CLI, OpenCode, Gemini CLI) that runs an LLM with tools.
- **Adapter:** the thin layer that packages the method for an operator and drives it headless.
- **Method:** the operator-neutral skills, roles, recipes and checklists.
- **Judge:** whatever produces the gate verdict: Jenkins, a CI artifact, or the local reference runner.
- **Evidence:** files written only by the core and verified by `forge audit`.
- **Checkpoint:** a phase transition that needs a human approval.
- **M0 to M3:** the run modes in Section 5.1.

## Appendix H: Sources consulted for the operator matrix (2026-10-30)

- Agent Skills standard and adopters: agentskills.io (official list); secondary summaries at sumproduct.com, shiplight.ai, env.dev, agentman.ai (ecosystem report 2026).
- Codex CLI hooks: developers.openai.com/codex/hooks (official, to be fetched in Phase 0); community notes at codex.danielvaughan.com (2026-03-27), docs.rs agent-config crate docs, pivanov.github.io/agent-hooks-bridge.
- Gemini CLI hooks and skills: geminicli.com/docs/hooks and /docs/hooks/reference; devops.com "Google adds hooks to Gemini CLI"; openSUSE gemini-cli changelog (v0.26/v0.27); product transition note from docs.rs agent-config (secondary, unverified).
- Cursor hooks: cursor.com/docs/agent/hooks; forum.cursor.com threads on CLI hook events and Windows firing issues.
- Copilot CLI and OpenCode hook details: from the author's knowledge; to be verified in Phase 0 task 0.3.

---

## Change log

| Date | Change | By |
|------|--------|----|
| 2026-10-30 | Version 1 written from a full repository read | Claude (for Pushpesh Pant) |
