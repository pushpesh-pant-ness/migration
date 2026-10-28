---
description: Fix what the Jenkins quality gate reported failing, at the root cause (never by weakening checks), then hand the new commit back to Jenkins, up to max_remediation_iterations; escalate to the human with a report when stuck. Use when the imported Jenkins verdict is FAIL, or when the user asks to fix vulnerabilities, secrets, PII, failing tests, eval failures or DB parity problems.
argument-hint: (no arguments)
---

# Remediate

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

1. Run `F state.py phase remediate`. Read `forge/gates/latest.json` and the iteration's `feedback.md`. The feedback lists each failing threshold and the top `file:line - rule - message` findings.
2. **Budget.** Count the consecutive FAIL entries at the end of `gate_history` in state. If that count is greater than `max_remediation_iterations` (settings), jump straight to **Escalate**.
3. **Triage.** Group the failures by gate, then by file or module:
   - **gate1** static analysis and security: Sonar issues, Semgrep, Trivy vulnerabilities and misconfigurations.
   - **gate2** secrets, hardcoded credentials, PII/PHI, PII in logs.
   - **gate3** Claude cost budget. Code can't fix this, so go straight to **Escalate**.
   - **gate4** functional evals: the failing case ids and why.
4. **Fix.** Delegate each group to a `remediation-engineer` agent, with its part of `feedback.md`.
   - Groups touching **different files** may run in parallel, in one message.
   - Groups touching the **same files** run one after another.
   - Order: secrets/credentials, then security, then PII, then functional evals, then DB, then static analysis.

   For each security finding, first run `/claude-security` "suggest patches" for that area. Hand the patch file to the engineer to review and adapt.
5. **Stop if a human is needed.** If any agent returns `needs_human`, stop the loop. Ask the human that question with AskUserQuestion, then continue.
6. **Hand back to Jenkins.** Run the project tests locally, commit (`git commit -m "forge: remediation for iteration N"`), then follow `/migration-forge:gate` steps 2–4 to get and import the verdict for the new commit.
   - The Stop hook lets the turn end while Jenkins builds the new commit. Say clearly that you are waiting for that build.
7. **No-progress rule.** If two consecutive verdicts fail with the same set of `check + reason`, escalate. Do not wait for the cap.

## Escalate
1. Write `forge/ESCALATION.md` containing:
   - the iterations tried and their Jenkins builds
   - for each failure still remaining: root cause, what was tried, and why it failed
   - the decision needed from the human, with options. Examples: accept a risk with an owner, change scope, legacy behavior is a bug, a threshold change (the Jenkins pipeline owners decide that), or a larger cost budget.
2. Run `F state.py phase escalated`. Then tell the human, briefly.
