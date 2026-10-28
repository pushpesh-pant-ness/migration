# Third-party components

Migration Forge does **not vendor** third-party skills or agents. It orchestrates them as separately installed plugins:

| Component | Source | Licence | How it's used |
|-----------|--------|---------|---------------|
| code-modernization | anthropics/claude-plugins-official | Apache-2.0 | required dependency (assess, map, rules, brief, build tracks, verify, harden) |
| claude-security | anthropics/claude-plugins-official | see plugin | required dependency (verified security scan + patches) |
| security-guidance | anthropics/claude-plugins-official | see plugin | required dependency (edit-time security hook) |
| context7 | anthropics/claude-plugins-official (external_plugins) | see plugin | required dependency (current library docs) |
| superpowers | obra/superpowers | MIT | optional (TDD, worktrees, verification-before-completion) |
| mattpocock-skills | mattpocock/skills | MIT | optional (grill-with-docs, to-spec, to-tickets) |
| Trail of Bits skills | trailofbits/skills | CC-BY-SA-4.0 | optional, installed as plugins only, never copied or modified |
| framework-migration, c4-architecture, database-migrations | wshobson/agents | MIT | optional |

External tools that the gates invoke if they are installed: Semgrep, gitleaks, Trivy, npm audit, pip-audit, squawk, Infracost, k6. Each is under its own licence.
