---
name: setup
description: Check and install what Migration Forge needs - Python and git, optional tools (docker for disposable DBs, squawk, infracost, semgrep/gitleaks/trivy), DB drivers, the Jenkins connection for gate verdicts, and the host tool's guard wiring - plus optional companion plugins for tools that have them. Use on first install or when a step reports a missing tool.
argument-hint: (no arguments)
disable-model-invocation: true
---

`forge` = `"<forge-root>/bin/forge"` (Windows shells: `bin\forge.cmd`). `<forge-root>` is this toolkit's folder: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, otherwise `$FORGE_ROOT` (see `AGENTS.md`).

1. **Check the tools.** Run `forge doctor` and show its output. Ask before installing anything on the machine. You may give the install commands to the user, or run them if they say yes.
   - **The quality gates and behavioral evals run in the team's Jenkins pipeline.** Ask for the URL of the build's `summary.json` artifact, and suggest the user puts it in `forge/settings.json` as `jenkins.results_url`. For a private Jenkins, the user sets `JENKINS_USER` and `JENKINS_TOKEN` in their own environment. Never ask for a token in chat. In a sandbox without network access to Jenkins, the human downloads `summary.json` (with `gate*.json` and `feedback.md`) into the workspace and the gate skill imports the local path.
2. **Guard wiring for the host tool.** There are no required plugins. Make sure the workspace rules are enforced where the work runs (see `AGENTS.md`, "Enforcing the rules"):
   - **Claude Code:** the plugin's hooks do it. Nothing to install.
   - **Other agents with a pre-tool or pre-command hook:** call `forge guard path <file>` before writes and `forge guard cmd "<command>"` before shell commands. Exit 2 blocks, 3 asks the human.
   - **Every tool:** `forge install-git-hooks` in the workspace. In a container sandbox, mount the legacy repo read-only.
   - **Approvals:** if the tool runs shell commands without asking, suggest `approvals.require_tty: true` in `forge/settings.json` so only the human can approve, from their own terminal.
3. **Optional companions.** The built-in skills cover every phase. If the user's tool has a plugin system and they want extras, offer each with its purpose, and install only the ones they pick. For Claude Code:
   ```
   /plugin install code-modernization@claude-plugins-official    # alternative assess/build/verify commands
   /plugin install claude-security@claude-plugins-official       # security scan + patches (used by harden/remediate if present)
   /plugin install context7@claude-plugins-official              # current library docs for the stack researcher
   /plugin install superpowers@claude-plugins-official           # TDD, worktrees, verification-before-completion
   /plugin marketplace add trailofbits/skills
   /plugin install static-analysis@trailofbits
   /plugin marketplace add wshobson/agents
   /plugin install framework-migration@claude-code-workflows     # angular-migration, react-modernization, dependency-upgrade
   ```
   Trail of Bits skills are CC-BY-SA-4.0. They are installed as plugins, not copied.
4. **Database drivers** for `forge db`. Install these only if the user will use the optional DB-migration track (`--with-db`), and skip this step otherwise. Install only the drivers the user needs: `pip install "psycopg[binary]"` for Postgres, `pymysql` for MySQL, and `pyodbc` for SQL Server (which also needs the Microsoft ODBC Driver 18).
5. **Optional Jira.** If the user has Jira and their tool has a Jira connector (for example the Atlassian MCP server), they can connect it. The local tracker stays the source of truth either way.
