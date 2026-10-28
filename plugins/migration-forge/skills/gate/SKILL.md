---
description: Get the migration quality-gate verdict from the Jenkins pipeline (which runs the static analysis, security, secrets/PII, cost and behavioral eval gates) for the current commit, record it, and act on it - close tickets on PASS, remediate on FAIL. Use after any build or remediation step, or when the user asks whether the gates pass.
argument-hint: [<summary.json path or Jenkins artifact URL>] [--commit <sha>] [--build <n>]
---

# Gate (verdict from Jenkins)

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

The gates and behavioral evals run in the team's Jenkins pipeline, not in this session. This skill brings their verdict in, so tickets, phases and remediation follow it.

1. Run `F state.py phase gate`.
2. **Make sure Jenkins tests this code.**
   - Commit everything (`git add -A && git commit -m "forge: ready for gate"`).
   - Jenkins builds what is pushed. Push only if the human has told you to push in this run. Otherwise ask them to push, or to start the build, and to tell you when it has finished.
3. **Find the result.** Use `$ARGUMENTS` if given. Otherwise use `jenkins.results_url` from settings, or ask the human for the build's `summary.json` path or artifact URL, plus the commit it built (`GIT_COMMIT` in the build).
   - For private Jenkins URLs the human sets `JENKINS_USER` and `JENKINS_TOKEN` in the environment. Never ask them to paste a token into chat.
4. **Import it:** `F jenkins_result.py import <location> --commit <sha> [--build <n>]`.
   - It refuses a baseline phase, a result already imported, and a result for a different commit than HEAD. Never work around a refusal: get the right build.
   - It writes `forge/gates/iteration-N/` (the pipeline's `summary.json`, `gate*.json` and `feedback.md`) and `forge/gates/latest.json`. Exit code 0 means PASS and 2 means FAIL.
5. **Decide.**
   - **PASS:** report it. If the phase is verify or harden, move forward. Otherwise close the tickets in review as the `/migration-forge:tracker` "Closing a ticket" rules describe.
   - **FAIL:** run `/migration-forge:remediate` immediately, without asking, unless `max_remediation_iterations` is exhausted. The Stop hook won't let the turn end on a FAIL while budget remains, until a fix is committed and waiting for Jenkins.
6. Commit with `git add -A && git commit -m "forge: jenkins verdict iteration N <verdict>"`.

## Report format
```
Jenkins gate iteration N — VERDICT  (phase after, build #123, commit abc1234)
gate1 Static analysis & security   FAIL  semgrep_high = 2 (required <= 0)
gate2 Secrets, credentials & PII   pass
gate3 Claude cost budget           pass
gate4 Functional evals             FAIL  critical_failures = 1 (required <= 0)
Feedback: forge/gates/iteration-N/feedback.md
```

Thresholds live in the Jenkins pipeline and belong to its owners. If the human asks to relax one, point them to the pipeline team, and record the decision in `forge/decisions/`.
