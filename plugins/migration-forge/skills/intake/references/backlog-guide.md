# Backlog guide for migration work

## Standard foundation stories. Every run needs these, so adapt the wording.
| Key | Title | Typical AC |
|-----|-------|-----------|
| F1 | Characterization tests on legacy behavior | Given the legacy system at commit X, when the suite runs, then it records golden outputs for every P0 endpoint/report |
| F2 | Target scaffolding + CI pipeline | Given a clean checkout, when CI runs, then build, lint, typecheck, tests, and security scans all execute and report |
| F3 | *(only when `db_migration` is on)* Data migration (schema + data + rollback) | Given a copy of production-shaped data, when migrations run up/down/up, then the schema is restored, and db_verify reports a 100% row and checksum match |
| F4 | Security hardening | Given the modernized build, when the scanners and the harden review run, then there are 0 critical/high findings and 0 secrets |
| F5 | Cutover + rollback rehearsal | Given the runbook, when it is rehearsed on staging, then cutover finishes inside the downtime budget, and rollback restores service in under N minutes |
| F6 | Legacy decommission | Given N days of clean operation, when the legacy system is switched off, then no traffic and no data writes are lost |

When `db_migration` is off, replace F3 with "Existing DB compatibility": Given the unchanged production schema, when the modernized backend runs against a copy of it, then all P0 flows work with no DDL applied.

Dependencies: F1 blocks every module story. F2 blocks every module story. F3 blocks the module stories that need schema changes. Every module story blocks F5, and F5 blocks F6.

## Writing a module story
```
Title:  Migrate <feature> (<legacy module> → <target module>)
As a <user role> I want <feature> on the new stack so that <business value / risk removed>
AC:
- Given <state> When <action> Then <observable outcome>, identical to legacy (BR-12, BR-14)
- Given <edge: empty / max / invalid / unauthorized> When … Then …
- Given the modernized module When the Jenkins gate runs Then it passes and the module is PROVEN in VERIFICATION.md
```

## INVEST checklist
Each story is:
- **Independent**, or its dependency is explicit as `blocked_by`
- **Negotiable**
- **Valuable** to a named role
- **Estimable**
- **Small**: 8 points or fewer
- **Testable**: every AC maps to an acceptance test or a Jenkins eval case

## Priority heuristics
- **P0:** money movement, legal or compliance data, authn/authz, or anything that blocks three or more stories.
- **P1:** daily-use features.
- **P2:** admin and reporting.
- **P3:** cosmetic.
