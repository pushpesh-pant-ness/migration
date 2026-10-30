---
name: harden
description: Security review of the modernized code (or a baseline of the legacy code) - OWASP/CWE checklist, local scanners when installed, every finding confirmed or refuted by reading the code, fixes in the modernized tree and a patch-for-review for legacy - recorded in SECURITY_FINDINGS.md, then the Jenkins gate and the release approval. Use in the harden phase, for the legacy security baseline during discovery, or when the user asks for a security review.
argument-hint: [legacy-baseline]
---

# Harden

`forge` = `"<forge-root>/bin/forge"` (Windows shells: `bin\forge.cmd`). `<forge-root>` is this toolkit's folder: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, otherwise `$FORGE_ROOT` (see `AGENTS.md`).

Two modes:
- **legacy-baseline** (from the discover skill, or `$ARGUMENTS` = `legacy-baseline`): review `legacy/<name>` to learn which weaknesses must not be carried over. Read-only: write no fix into legacy. Don't change the phase.
- **harden** (default): run `forge state phase harden` and review the modernized code.

If your tool has a security-review skill or plugin (for example `claude-security` in Claude Code), you may run it first and use its findings as candidates. Every candidate still goes through step 3.

## Steps
1. **Scan** with what is installed (`forge doctor` lists them), and say which ones were missing:
   - `semgrep scan --config p/default --json <dir>`
   - `gitleaks detect --source <dir> --no-git --report-format json --report-path scratch/gitleaks.json`
   - `trivy fs --scanners vuln,misconfig --format json <dir>`
   - the stack's own audit: `npm audit --json`, `pip-audit`, `dotnet list package --vulnerable`, `mvn dependency-check:check`
2. **Review by hand** what scanners miss, against the OWASP Top 10: access control on every route, injection (SQL, command, template), authentication and session handling, secrets in code or config, crypto choices, input validation, SSRF, unsafe deserialization, PII in logs, and security headers/CORS.
3. **Confirm or refute each finding** by reading the code path: is it reachable with attacker-controlled input? Record refuted ones with the reason. Don't drop them silently.
4. **Write `analysis/<name>/SECURITY_FINDINGS.md`:** one row per finding with id, severity (critical/high/medium/low), CWE, file:line, evidence, status (confirmed/refuted), and the fix or the reason for no fix. Mask secrets: first 4 characters only.
5. **Act.**
   - **harden:** fix confirmed critical and high findings in the modernized code, following `agents/remediation-engineer.md` (root cause, no suppressions). Re-run the tests. Commit.
   - **legacy-baseline:** save a summary as `forge/evidence/legacy-security-baseline.json` (`{"tool": [...], "findings": [{"id", "severity", "cwe", "file", "line", "status"}]}`) and, for critical findings, a patch file under `forge/evidence/legacy-patches/` for the human to apply themselves. Never apply it to legacy.
6. **harden only:** follow the `gate` skill so Jenkins checks this commit. On PASS, run the **approve release** checkpoint from the migrate skill: show the findings fixed and remaining, the verification verdicts, and the Jenkins verdict.
