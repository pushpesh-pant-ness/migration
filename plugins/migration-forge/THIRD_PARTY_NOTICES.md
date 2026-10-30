# Third-party components

Migration Forge has **no required third-party plugins or Python packages** and does **not vendor** third-party skills or agents. Its assessment, build, verification and hardening playbooks are its own.

Optional companions a host tool may have installed. The skills use them when present and never fail without them:

| Component | Source | Licence | How it's used |
|-----------|--------|---------|---------------|
| code-modernization | anthropics/claude-plugins-official | Apache-2.0 | optional, Claude Code: alternative assess/build/verify commands |
| claude-security | anthropics/claude-plugins-official | see plugin | optional, Claude Code: security scan + patch candidates for harden/remediate |
| context7 | anthropics/claude-plugins-official (external_plugins) | see plugin | optional: current library docs for the stack researcher |
| superpowers | obra/superpowers | MIT | optional (TDD, worktrees, verification-before-completion) |
| Trail of Bits skills | trailofbits/skills | CC-BY-SA-4.0 | optional, installed as plugins only, never copied or modified |
| framework-migration, c4-architecture, database-migrations | wshobson/agents | MIT | optional |

External tools the scripts or skills invoke if they are installed: git (required), squawk, Infracost, semgrep, gitleaks, trivy, docker, and the database drivers for db_verify.py. Each is under its own licence. The quality-gate scanners run in the team's Jenkins pipeline, not in this toolkit.
