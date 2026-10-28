---
description: Run the migration quality gate - tests, coverage, types, lint, security (Semgrep, gitleaks, Trivy, dependency audits, claude-security verified scan), behavioral evals, database parity/reversibility, cost and optional performance - score it against thresholds, and have the gatekeeper audit the evidence. Proceed only on PASS. Use after any build/remediation step or when the user asks to check quality, security, cost or evals.
argument-hint: [--only tests,security,...]
---

# Gate

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

1. Run `F state.py phase gate`. If `modernized_root` is not set in state, find it and set it first.
2. **Collect the evidence agents must produce.** Run independent items in parallel in one message.
   - **Security (semantic):** run `/claude-security` with "scan changes" against the base branch, or "scan codebase" on `<modernized_root>` for the first gate, at depth high. From its report, count **verified** findings by severity and write `forge/evidence/claude-security.json`:
     `{"critical":0,"high":0,"medium":0,"low":0,"report":"<path to its report>","scope":"<what was scanned>","at":"<date>"}`
     Report the counts exactly as written in the report. Do not down-rank anything.
   - **Code review** (the `review` check) of `git diff <base_ref>...HEAD` for the modernized tree. `base_ref` comes from state.
     1. Run the built-in `/code-review high` on that range. It covers correctness bugs, reuse, and simplification.
     2. Run code-modernization's `architecture-critic` agent against `forge/decisions/ADR-001-target-stack.md` and `MODERNIZATION_BRIEF.md`. It covers drift from the decided stack and boundaries, and legacy anti-patterns carried over: god modules, string-built SQL, global state, and copy-pasted legacy logic.
     3. If `pr-review-toolkit` is installed, its agents may add findings.
     4. Merge and dedupe the findings, then classify each one:
        - **blocking:** a confirmed correctness bug, a security issue, or an ADR violation in a P0 module
        - **major:** a maintainability problem that will cost real effort later, such as duplication, a ported anti-pattern, or dead code
        - **minor:** everything else
     5. Write `forge/evidence/code-review.json`:
        `{"base":"<sha>","reviewers":["code-review","architecture-critic"],"blocking":0,"major":0,"minor":0,"findings":[{"severity":"major","file":"","line":0,"summary":"","source":"architecture-critic"}]}`
     The counts must equal the findings list. The gatekeeper checks this.
   - **Optional deeper checks** (if the Trail of Bits plugins are installed): `supply-chain-risk-auditor` on the manifests and `insecure-defaults` on the config. List their high findings in the same JSON under `"advisory"`. They don't count toward the thresholds unless you add them to `high`.
   - **Behavior:**
     1. Run `F env.py status`. If it fails or `forge/env/env.json` is missing, run `/migration-forge:env` first (setup or up). If the code changed since the last gate, run `F env.py up` so the `new` service is rebuilt.
     2. Run `F evals_run.py`: all cases (http_diff, ui_e2e, command, plus sql_diff on the DB track), every gate.
   - **Database** (only when `db_migration` is true): if any migration or transform changed since `forge/db/verify.json` was written, run the `db-migration-engineer` agent in **verify** mode first. When the track is off, the database check reports n/a and is excluded from the score.
   - **Performance** (optional): if `forge/perf/k6-legacy.json` exists, run the same k6 script against the new system with `k6 run --summary-export forge/perf/k6-modernized.json <script>`.
3. **Score.** Run `F run_gates.py` (pass `$ARGUMENTS` through to `--only`, if given). It prints the verdict and writes `forge/gates/iteration-N/scorecard.json`. Exit code 0 means PASS and 2 means FAIL.
4. **Audit.** Delegate to the `gatekeeper` agent, then save its JSON to `forge/evidence/gatekeeper-iteration-<N>.json`.
5. **Decide.**
   - **PASS:** both the scorecard and the gatekeeper must say PASS. Report the table below. If the current phase is verify or harden, move forward. Otherwise close the tickets in review as the `/migration-forge:tracker` "Closing a ticket" rules describe.
   - **FAIL:** run `/migration-forge:remediate` immediately. Don't ask, unless `max_remediation_iterations` is exhausted. The Stop hook will not let the turn end on a FAIL while budget remains.
6. Commit with `git add -A && git commit -m "forge: gate iteration N <verdict>"`.

## Report format
```
Gate iteration N — VERDICT (overall X / min Y)   gatekeeper: PASS|FAIL
check        req  status   score  detail
tests        ✔    pass     100    412/412
coverage     ✔    FAIL      91    72.4% < 80%
...
Blockers: <top 3 with evidence paths>
```

Thresholds come from `${CLAUDE_PLUGIN_ROOT}/config/gates.json`, overridden by `forge/gates.json`. Only the human changes them. If the human asks you to relax a threshold, tell them to edit `forge/gates.json` themselves, and record the decision in `forge/decisions/`.
