---
description: Fix failing migration gate checks at the root cause (never by weakening checks), then re-gate, up to max_remediation_iterations; escalate to the human with a report when stuck. Use when a gate is FAIL, or when the user asks to fix vulnerabilities, failing tests, coverage, eval or DB parity problems.
argument-hint: [auto]  (auto = run the deterministic gate-loop workflow)
---

# Remediate

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

1. Run `F state.py phase remediate`. Read `forge/gates/latest.json` and the latest `forge/evidence/gatekeeper-iteration-*.json`.
2. **Budget.** Count the consecutive FAIL entries at the end of `gate_history` in state. If that count is greater than `max_remediation_iterations`, jump straight to **Escalate**.
3. **Triage.** Merge the scorecard `failures` (already sorted with blockers first and by weight) with the gatekeeper's `confirmed_failures`. Group them by check, then by file or module.
4. **Fix.** Delegate each group to a `remediation-engineer` agent.
   - Groups touching **different files** may run in parallel, in one message.
   - Groups touching the **same files** run one after another.
   - Order: security, then behavior, then DB, then review, then tests, then types, then coverage, then lint, then cost.

   For each security finding, first run `/claude-security` "suggest patches" for that report. Hand the patch file to the engineer to review and adapt.
5. **Stop if a human is needed.** If any agent returns `needs_human`, stop the loop. Ask the human that question with AskUserQuestion, then continue.
6. **Re-gate.** Run `/migration-forge:gate`. That is a full gate, which keeps the evidence honest.
7. **No-progress rule.** If two consecutive iterations fail with the same set of `check + reason`, escalate. Do not wait for the cap.

## Auto mode (`$ARGUMENTS` = auto)
Run the workflow `/migration-forge:gate-loop` with args `{"name":"<name>","plugin_root":"${CLAUDE_PLUGIN_ROOT}","max_iterations":<cap>}`. It runs gate, then gatekeeper, then remediation, and re-gates deterministically, then returns the final verdict. Afterwards, read `forge/gates/latest.json` and report.

## Escalate
1. Write `forge/ESCALATION.md` containing:
   - the iterations tried and their scores
   - for each failure still remaining: root cause, what was tried, and why it failed
   - the decision needed from the human, with options. Examples: accept a risk with an owner, change scope, legacy behavior is a bug, or relax a threshold (they must edit `forge/gates.json` themselves).
2. Run `F state.py phase escalated`. Then tell the human, briefly.
