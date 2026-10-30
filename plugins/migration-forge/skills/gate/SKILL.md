---
name: gate
description: Get the migration quality-gate verdict from the Jenkins pipeline (which runs the static analysis, security, secrets/PII, cost and behavioral eval gates) for the current commit, record it, and act on it - close tickets on PASS, remediate on FAIL. Use after any build or remediation step, or when the user asks whether the gates pass.
argument-hint: [<summary.json path or Jenkins artifact URL>] [--commit <sha>] [--build <n>]
---

# Gate (verdict from Jenkins)

`forge` = `"<forge-root>/bin/forge"` (Windows shells: `bin\forge.cmd`). `<forge-root>` is this toolkit's folder: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, otherwise `$FORGE_ROOT` (see `AGENTS.md`).

The gates and behavioral evals run in the team's Jenkins pipeline, not in this session. This skill brings their verdict in, so tickets, phases and remediation follow it.

1. Run `forge state phase gate`. It remembers which build phase the gate is checking (execute, verify or harden) as `gate_context`, and `forge next` uses it after a PASS.
2. **Make sure Jenkins tests this code.**
   - Commit everything (`git add -A && git commit -m "forge: ready for gate"`).
   - Jenkins builds what is pushed. Push only if the human has told you to push in this run. Otherwise ask them to push, or to start the build, and to tell you when it has finished.
3. **Find the result.** Use the arguments if given (`$ARGUMENTS`). Otherwise use `jenkins.results_url` from settings, or ask the human for the build's `summary.json` path or artifact URL, plus the commit it built (`GIT_COMMIT` in the build).
   - A local path works too, for example a `summary.json` the human downloaded into a sandbox with no network access to Jenkins. Keep `gate*.json` and `feedback.md` next to it.
   - For private Jenkins URLs the human sets `JENKINS_USER` and `JENKINS_TOKEN` in the environment. Never ask them to paste a token into chat.
4. **Import it:** `forge gate import <location> --commit <sha> [--build <n>]`.
   - It refuses a baseline phase, a result already imported, a result for a different commit than HEAD, and a PASS without `--commit` (unless `summary.json` names the commit itself). Never work around a refusal: get the right build.
   - It writes `forge/gates/iteration-N/` (the pipeline's `summary.json`, `gate*.json` and `feedback.md`) and `forge/gates/latest.json`. Exit code 0 means PASS and 2 means FAIL.
5. **Decide.**
   - **PASS:** report it, then run `forge next`: it says what follows for the phase the gate was checking. After **execute**, close the tickets in review as the `tracker` skill's "Closing a ticket" rules describe, then continue with the next ticket or wave, or `forge state phase verify` when every wave is done. After **verify**, `forge state phase harden`. After **harden**, the approve release checkpoint, then `forge state phase done`. verify, harden and done are refused without a commit-verified PASS for the current code.
   - **FAIL:** follow the `remediate` skill immediately, without asking, unless `max_remediation_iterations` is exhausted. `forge next` exits 3 (and in Claude Code the Stop hook won't let the turn end) on a FAIL while budget remains, until a code fix is committed and waiting for Jenkins. Committing only `forge/` (this verdict, a phase move) does not count as a fix.
6. Commit with `git add -A && git commit -m "forge: jenkins verdict iteration N <verdict>"`.

## Report format
```
Jenkins gate iteration N — VERDICT  (phase after, build #123, commit abc1234)
gate1 Static analysis & security   FAIL  semgrep_high = 2 (required <= 0)
gate2 Secrets, credentials & PII   pass
gate3 Cost budget                  pass
gate4 Functional evals             FAIL  critical_failures = 1 (required <= 0)
Feedback: forge/gates/iteration-N/feedback.md
```

Thresholds live in the Jenkins pipeline and belong to its owners. If the human asks to relax one, point them to the pipeline team, and record the decision in `forge/decisions/`.
