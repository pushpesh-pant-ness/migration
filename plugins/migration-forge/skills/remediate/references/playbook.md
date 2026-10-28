# Remediation playbook (root-cause first)

| Check | Typical root cause | Fix pattern | Never |
|-------|-------------------|-------------|-------|
| tests | behavior drift vs legacy; async/timezone flakiness; env assumptions | compare with the legacy code path and BR-*; fix code, or fix a wrong test only if it contradicts legacy/BR (note why) | delete, skip, loosen assertions |
| review | ported legacy anti-pattern, duplication, drift from the ADR or brief, a real bug | fix the design (extract module, use the framework idiom the ADR chose); bugs get a failing test first | arguing the finding away, or renaming things without fixing them |
| coverage | untested branches in migrated code (gated on changed lines) | add tests for real behavior (error paths, edge cases from migration-evals catalogue) | trivial assertion-free tests, excluding files from coverage |
| typecheck | `any` leakage, wrong nullability after port | real types at boundaries (DTOs, DB rows), narrow unions | `@ts-ignore`, `any` casts, `# type: ignore` |
| lint | style + real smells | autofix (`eslint --fix`, `ruff --fix`) then manual | blanket disable comments |
| security: injection | string-built SQL, unsanitized HTML | parameterized queries / ORM bind params; framework output encoding; CSP | escaping by hand, regex "sanitizers" |
| security: authz | ported route lost middleware/guard | port the guard; deny-by-default; test for 401/403 | trusting client-side checks |
| security: secrets | hardcoded creds copied from legacy | move to env/secret manager; rotate (tell human); add to SECRETS.local.md | committing `.env`, allowlisting the finding |
| security: deps | vulnerable versions | upgrade to fixed version within the ADR's major; if none, replace or document mitigation | `npm audit fix --force` across majors without tests |
| security: IaC/misconfig | open ports, public buckets, root containers | least privilege, non-root user, pinned base images | ignoring trivy misconfig |
| behavior (http_diff) | serialization (dates, decimals, nulls, key order), pagination, error shapes | match legacy contract, or create an explicit "accepted difference" approved by human | adding fields to `ignore` without reason |
| behavior (NOT PROVEN) | module not exercised by proof pack | run modernize-verify for that module; add characterization tests | marking PROVEN manually |
| database parity | type coercion (bool/tinyint, money/decimal, tz), truncation, charset, missed rows in batch copy | fix transform; re-run copy; re-seed sequences | excluding columns/tables to hide drift |
| database reversibility | down migration missing or lossy | write proper down; for destructive steps use expand/contract (keep old column until contract) | marking irreversible without human approval |
| cost | parallelism too wide, strongest model everywhere, large re-reads | narrow scope, smaller model for mechanical stages, pilot-first | stopping verification to save tokens |
