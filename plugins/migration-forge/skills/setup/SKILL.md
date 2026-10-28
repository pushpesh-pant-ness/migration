---
description: Check and install what Migration Forge needs - Docker (runs SonarQube and, when not installed locally, Semgrep/Gitleaks/Trivy), optional local scanners and tools (squawk, infracost, k6), DB drivers, the corporate CA for TLS-inspecting proxies, and the optional companion plugins (Superpowers, Matt Pocock skills, Trail of Bits, wshobson framework-migration/c4/database-migrations). Use on first install or when a gate reports a missing tool.
argument-hint: (no arguments)
disable-model-invocation: true
---

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

1. **Check the tools.** Run `F doctor.py` and show its output. Ask before installing anything on the machine. You may give the install commands to the user, or run them if they say yes.
   - **Docker is the one hard requirement for the gates.** SonarQube always runs in it, and Semgrep/Gitleaks/Trivy run in it unless they are installed locally. Give Docker Desktop at least 4 GB RAM. `F sonar.py up` starts SonarQube once (2–5 minutes) and stores a generated admin password in `~/.migration-forge/sonar.json`.
   - **Behind a TLS-inspecting proxy** (Netskope, Zscaler): if image pulls or rule downloads fail with certificate errors, ask the user to save their corporate root CA as `~/.migration-forge/corporate-ca.pem` (or set `FORGE_CA_CERT`). The scanner containers then trust it. Never commit it.
2. **Required plugins.** These are declared as dependencies and auto-installed: `code-modernization`, `claude-security`, `security-guidance`, and `context7`, all from `claude-plugins-official`. Confirm they are enabled with `/plugin`. If one is missing, have the user run `/plugin install <name>@claude-plugins-official`.
3. **Optional companions.** Offer each one with its purpose, and install only the ones the user picks. Give the user these commands to run in the Claude Code prompt:
   ```
   /plugin install superpowers@claude-plugins-official           # TDD, worktrees, verification-before-completion
   /plugin install mattpocock-skills@claude-plugins-official     # grill-with-docs, to-spec, to-tickets
   /plugin marketplace add trailofbits/skills
   /plugin install static-analysis@trailofbits
   /plugin install supply-chain-risk-auditor@trailofbits
   /plugin install insecure-defaults@trailofbits
   /plugin install differential-review@trailofbits
   /plugin marketplace add wshobson/agents
   /plugin install framework-migration@claude-code-workflows     # angular-migration, react-modernization, dependency-upgrade, database-migration skills
   /plugin install c4-architecture@claude-code-workflows         # c4-context/container/component/code agents
   /plugin install database-migrations@claude-code-workflows     # database-admin, database-optimizer agents
   ```
   Trail of Bits skills are CC-BY-SA-4.0. They are installed as plugins, not copied.
4. **Database drivers** for `db_verify.py`. Install these only if the user will use the optional DB-migration track (`--with-db`), and skip this step otherwise. Install only the drivers the user needs: `pip install "psycopg[binary]"` for Postgres, `pymysql` for MySQL, and `pyodbc` for SQL Server (which also needs the Microsoft ODBC Driver 18).
5. **Optional Jira.** If the user has Jira, they can connect the Atlassian MCP connector. The local tracker stays the source of truth either way.
