---
name: remediate
description: Fix what the Jenkins quality gate reported failing, at the root cause (never by weakening checks), then hand the new commit back to Jenkins, up to max_remediation_iterations; escalate to the human with a report when stuck. Use when the imported Jenkins verdict is FAIL, or when the user asks to fix vulnerabilities, secrets, PII, failing tests, eval failures or DB parity problems.
argument-hint: (no arguments)
---

# Remediate

`forge` = `"<forge-root>/bin/forge"` (Windows shells: `bin\forge.cmd`). `<forge-root>` is this toolkit's folder: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, otherwise `$FORGE_ROOT` (see `AGENTS.md`).

1. Run `forge state phase remediate`. Read `forge/gates/latest.json` and the iteration's `feedback.md`. The feedback lists each failing threshold and the top `file:line - rule - message` findings.
2. **Budget.** Count the consecutive FAIL entries at the end of `gate_history` in state. If that count is greater than `max_remediation_iterations` (settings), jump straight to **Escalate**.
3. **Triage.** Group the failures by gate, then by file or module:
   - **gate1** static analysis and security: Sonar issues, Semgrep, Trivy vulnerabilities and misconfigurations.
   - **gate2** secrets, hardcoded credentials, PII/PHI, PII in logs.
   - **gate3** cost budget. Code can't fix this, so go straight to **Escalate**.
   - **gate4** functional evals: the failing case ids and why.
4. **Fix.** Delegate each group to a `remediation-engineer` role (`<forge-root>/agents/remediation-engineer.md`), with its part of `feedback.md`. Without subagents, work through the groups yourself following that file.
   - Groups touching **different files** may run in parallel.
   - Groups touching the **same files** run one after another.
   - Order: secrets/credentials, then security, then PII, then functional evals, then DB, then static analysis.

   For security findings, follow step 3 of the `harden` skill to confirm each one and choose the secure pattern. A security-review tool (for example `claude-security` in Claude Code) may suggest patches; the engineer reviews and adapts them.
5. **Stop if a human is needed.** If any group returns `needs_human`, stop the loop. Ask the human that question, then continue.
6. **Hand back to Jenkins.** Run the project tests locally, commit (`git commit -m "forge: remediation for iteration N"`), then follow the `gate` skill, steps 2–4, to get and import the verdict for the new commit.
   - Once the fix is committed, `forge next` (and the Claude Code Stop hook) lets the turn end while Jenkins builds the new commit. Say clearly that you are waiting for that build. Only a commit that changes code outside `forge/` counts as the fix.
7. **No-progress rule.** If two consecutive verdicts fail with the same set of `check + reason`, escalate. Do not wait for the cap.

## Escalate
1. Write `forge/ESCALATION.md` containing:
   - the iterations tried and their Jenkins builds
   - for each failure still remaining: root cause, what was tried, and why it failed
   - the decision needed from the human, with options. Examples: accept a risk with an owner, change scope, legacy behavior is a bug, a threshold change (the Jenkins pipeline owners decide that), or a larger cost budget.
2. Run `forge state phase escalated`. Then tell the human, briefly.
