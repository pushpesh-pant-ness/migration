# Remediation playbook (root-cause first)

The rows follow what the Jenkins gates report: gate1 is static analysis and security, gate2 is secrets/PII, gate4 is functional evals.

| Finding | Typical root cause | Fix pattern | Never |
|-------|-------------------|-------------|-------|
| tests (local) | behavior drift vs legacy; async/timezone flakiness; env assumptions | compare with the legacy code path and BR-*; fix code, or fix a wrong test only if it contradicts legacy/BR (note why) | delete, skip, loosen assertions |
| static analysis (Sonar bugs, smells, duplication, ratings) | ported legacy anti-pattern, duplication, drift from the ADR or brief, a real bug | fix the issue Sonar names; extract duplicates; use the framework idiom the ADR chose; bugs get a failing test first | `//NOSONAR`, new exclusions, marking issues "won't fix" without a human |
| security: injection | string-built SQL, unsanitized HTML | parameterized queries / ORM bind params; framework output encoding; CSP | escaping by hand, regex "sanitizers" |
| security: authz | ported route lost middleware/guard | port the guard; deny-by-default; test for 401/403 | trusting client-side checks |
| security: deps | vulnerable versions | upgrade to fixed version within the ADR's major; if none, replace or document mitigation | `npm audit fix --force` across majors without tests |
| security: IaC/misconfig | open ports, public buckets, root containers | least privilege, non-root user, pinned base images | ignoring the misconfig |
| secrets / hardcoded credentials | creds or tokens copied from legacy config | move to env/secret manager; tell the human to rotate; add to SECRETS.local.md | committing `.env`, allowlisting the finding, renaming `password` to dodge the pattern |
| PII / PHI in code or seed data | real-looking SSNs, e-mails, phones in fixtures and seeds | synthetic data on fake domains (`@example.com`) | suppressing it, or copying production data "just for tests" |
| PII in logs | PII values passed to loggers | log ids, not values; mask before logging | renaming variables to dodge the scanner |
| functional eval (gate4) | intended change not implemented (validation, 404 vs 500, no SSN in responses), or behavior drift | implement it; the expected values come from the story/rule and the legacy code path | asking for the eval to be changed to match what the code does |
| database parity | type coercion (bool/tinyint, money/decimal, tz), truncation, charset, missed rows in batch copy | fix transform; re-run copy; re-seed sequences | excluding columns/tables to hide drift |
| database reversibility | down migration missing or lossy | write proper down; for destructive steps use expand/contract (keep old column until contract) | marking irreversible without human approval |
