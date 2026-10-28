---
description: Generate a CI pipeline (GitHub Actions by default; Jenkins, Azure DevOps or GitLab on request) that runs the same deterministic migration gate as the local session - scanners, SonarQube, PII scan, tests, changed-line coverage, side-by-side behavioral and UI evals, run_gates.py - so the thresholds keep holding after Claude leaves. Use when the user asks for CI/CD, a pipeline, or to enforce the gates on pull requests.
argument-hint: [github | jenkins | azure | gitlab]
disable-model-invocation: true
---

# CI handoff

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

1. **Preconditions.**
   - `forge/env/env.json` exists. If it doesn't, run `/migration-forge:env` first.
   - `modernized_root` and `base_ref` are set in state.
   - The workspace is a git repo with a remote. Ask the user for the legacy repo's `owner/name` and the frozen commit the migration started from.
2. **Vendor the gate**, so CI doesn't need Claude or the plugin. Copy these into `.forge-ci/` in the workspace:
   - `${CLAUDE_PLUGIN_ROOT}/scripts/*.py` → `.forge-ci/scripts/`
   - `${CLAUDE_PLUGIN_ROOT}/config/gates.json` → `.forge-ci/config/gates.json`. `forgelib.PLUGIN_ROOT` resolves to `.forge-ci/`, which is the parent of `scripts/`.
   - `${CLAUDE_PLUGIN_ROOT}/skills/ci/assets/gates.ci.json` → `.forge-ci/gates.ci.json`

   Add `.forge-ci/README.md` stating that the folder is generated, and that you re-run `/migration-forge:ci` to update it.
3. **Pin the versions now.** Follow the plugin's version policy: never from memory.
   - Fetch the latest releases of gitleaks (`https://api.github.com/repos/gitleaks/gitleaks/releases/latest`) and trivy (`.../aquasecurity/trivy/releases/latest`). Fetch `https://pypi.org/pypi/semgrep/json` and `.../diff-cover/json`.
   - Use the `tag_name` or `info.version` from each. Check that the release asset names match the URL patterns in the template. Trivy and gitleaks have renamed assets before.
4. **Fill the template.** Use `${CLAUDE_PLUGIN_ROOT}/skills/ci/assets/github-actions.yml` and replace every `{{…}}`:
   - `RUNTIME_SETUP`: setup steps for the target stack from `forge/decisions/target-stack.json`, such as `actions/setup-node@v4` with `node-version` or `actions/setup-java@v4`. Indent them as steps.
   - `INSTALL_COMMANDS`: the modernized code's install and build commands, for example `npm ci` (which keeps `node_modules` present for Trivy's licence scan).
   - `PIP_AUDIT`: `"pip-audit==<ver>"` if the stack is Python, otherwise empty.
   - `NAME`, `MODERNIZED_ROOT`, `DEFAULT_BRANCH`, `LEGACY_REPOSITORY`, `LEGACY_REF`, `PYTHON_VERSION`: the current Python LTS-equivalent minor.

   Write the result to `.github/workflows/forge-gates.yml`. For `azure` or `gitlab`, translate the same steps into `azure-pipelines.yml` or `.gitlab-ci.yml`. Keep the order identical: checkout, pinned tools, install, env up, evals, gate, upload evidence, env down.

   For `jenkins`, fill `${CLAUDE_PLUGIN_ROOT}/skills/ci/assets/Jenkinsfile` the same way (`LEGACY_REPOSITORY_URL` is the legacy repo's clone URL) and write it as `Jenkinsfile`.
   - It needs only Docker and Python on the agent. SonarQube always runs as a container, and the scanners fall back to their Docker images when they aren't installed (`scanners.prefer: auto`).
   - On GitHub Actions the same applies: `static` (SonarQube) runs in Docker on the runner.
   - Its optional `MODERNIZE_LOOP` stage shows the headless Claude loop with the spend ledger (`cost_estimate.py check / remaining / record-claude`).
5. **Explain the CI profile to the user.**
   - `gates.ci.json` relaxes only what CI can't produce without Claude: the claude-security summary, the code review, and transcript token cost.
   - Everything deterministic stays at the same thresholds.
   - The commented `claude-evidence` job restores those checks if they add an `ANTHROPIC_API_KEY` secret.
6. **Dry-run locally where possible.**
   - Run `FORGE_GATES_OVERRIDE=.forge-ci/gates.ci.json python .forge-ci/scripts/run_gates.py`. It should give the same verdict as the local gate, apart from the relaxed checks.
   - Do **not** push or open a PR unless the user asks. Report the files created.
