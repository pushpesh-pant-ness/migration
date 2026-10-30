#!/usr/bin/env python3
"""Migration Forge CLI: one entry point for every script, usable from any agent, sandbox, CI job or terminal.

  forge state   ...        run state, phases, approvals (state.py)
  forge tracker ...        local Jira-style backlog (tracker.py)
  forge gate    import|show   Jenkins quality-gate verdict (jenkins_result.py)
  forge db      ...        database migration evidence (db_verify.py)
  forge cost    [report|log]  token and infra cost (cost_estimate.py)
  forge doctor             check the tools the toolkit uses
  forge brief              five-line summary of the run in this workspace
  forge next               what is due now; exit 3 while a failing verdict must be remediated
  forge guard   path|cmd|legacy   workspace rules (exit 0 allow, 2 block, 3 ask a human)
  forge install-git-hooks  pre-commit hook in this workspace: refuse commits while the legacy source is modified
  forge root               print the toolkit folder (skills/, agents/, config/)

Run it as <forge-root>/bin/forge (POSIX shells), <forge-root>\\bin\\forge.cmd (Windows), or
python3 <forge-root>/scripts/forge.py. Stdlib only, Python >= 3.9.
"""
import os
import pathlib
import runpy
import stat
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from forgelib import FORGE_DIR, PLUGIN_ROOT, find_workspace, git_out, read_json, verdict_covers_code  # noqa: E402

SCRIPTS = {"state": "state.py", "tracker": "tracker.py", "gate": "jenkins_result.py", "db": "db_verify.py",
           "cost": "cost_estimate.py", "doctor": "doctor.py"}
# The skill to follow in each phase, for `forge next`.
NEXT = {"intake": "intake", "discover": "discover", "plan-stack": "plan-stack", "plan-migration": "plan-migration",
        "execute": "execute", "gate": "gate", "remediate": "remediate", "verify": "verify", "harden": "harden",
        "done": "status", "escalated": "status (read forge/ESCALATION.md with the human)"}
# What to do once the gate loop has a PASS for the current code, by the build phase it was checking (state.gate_context).
AFTER_PASS = {"execute": "close the reviewed tickets (tracker skill, 'Closing a ticket'), then `forge state phase execute` "
                         "for the next ticket or wave, or `forge state phase verify` once every wave is done",
              "verify": "`forge state phase harden`, then follow the harden skill",
              "harden": "run the approve release checkpoint (migrate skill), then `forge state phase done`"}


def run_script(name, argv):
    sys.argv = [str(HERE / name), *argv]
    runpy.run_path(str(HERE / name), run_name="__main__")


def cmd_next(_):
    from stop_gate import obligation
    ws = find_workspace(os.getcwd())
    if not ws:
        print("no migration workspace here: start one with the migrate skill (forge state init ...)")
        return 0
    reason = obligation(ws)
    if reason:
        print("MUST CONTINUE: " + reason)
        return 3
    st = read_json(ws / FORGE_DIR / "state.json", {}) or {}
    phase = st.get("phase")
    if phase in ("gate", "remediate"):
        ctx = st.get("gate_context") or "execute"
        if verdict_covers_code(ws, read_json(ws / FORGE_DIR / "gates" / "latest.json")):
            print(f"phase {phase}: the Jenkins gate PASSED for the current code (checking the {ctx} phase). "
                  f"Next: {AFTER_PASS.get(ctx, AFTER_PASS['execute'])}")
        else:
            print(f"phase {phase} (checking the {ctx} phase): follow the {NEXT[phase]} skill; "
                  "no commit-verified Jenkins PASS covers the current code yet")
        return 0
    print(f"phase {phase}: follow the {NEXT.get(phase, 'migrate')} skill"
          + ("; a human approval checkpoint may be pending (forge state show)" if phase in ("intake", "plan-stack", "plan-migration", "harden") else ""))
    return 0


def cmd_brief(_):
    from session_brief import brief
    ws = find_workspace(os.getcwd())
    print("\n".join(brief(ws)) if ws else "no migration workspace here")
    return 0


PRE_COMMIT = """#!/bin/sh
# migration-forge: refuse commits while the legacy source is modified
# The toolkit folder is the one at install time; $FORGE_ROOT overrides it (a plugin update may move the toolkit).
root="${{FORGE_ROOT:-{root}}}"
if [ ! -f "$root/scripts/forge.py" ]; then
  echo "migration-forge: toolkit not found at $root. Set FORGE_ROOT to it, or re-run: forge install-git-hooks" >&2
  exit 1
fi
py_at_install="{python}"
if [ -x "$py_at_install" ]; then
  exec "$py_at_install" "$root/scripts/forge.py" guard legacy
fi
for py in python3 python "py -3"; do
  if $py -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    exec $py "$root/scripts/forge.py" guard legacy
  fi
done
echo "migration-forge: Python >= 3.9 not found for the pre-commit check" >&2
exit 1
"""


def cmd_install_git_hooks(_):
    ws = find_workspace(os.getcwd())
    top = git_out(ws, "rev-parse", "--show-toplevel") if ws else None
    if not ws or not top or pathlib.Path(top.strip()).resolve() != ws.resolve():
        sys.exit("run this at the top of a migration workspace that is a git repository (git init first)")
    # --git-path follows linked worktrees (.git is a file there) and core.hooksPath.
    hooks = pathlib.Path(git_out(ws, "rev-parse", "--git-path", "hooks").strip())
    hook = (hooks if hooks.is_absolute() else ws / hooks) / "pre-commit"
    if hook.exists() and "migration-forge" not in hook.read_text(encoding="utf-8", errors="replace"):
        sys.exit(f"{hook} already exists; add this line to it yourself: \"{sys.executable}\" \"{HERE / 'forge.py'}\" guard legacy")
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(PRE_COMMIT.format(root=PLUGIN_ROOT.as_posix(), python=pathlib.Path(sys.executable).as_posix()),
                    encoding="utf-8", newline="\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"installed {hook}")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in SCRIPTS:
        run_script(SCRIPTS[cmd], rest)
        return 0
    if cmd == "guard":
        from guard import cli
        cli(rest)
        return 0
    if cmd == "root":
        print(PLUGIN_ROOT)
        return 0
    handlers = {"next": cmd_next, "brief": cmd_brief, "install-git-hooks": cmd_install_git_hooks}
    if cmd not in handlers:
        sys.exit(f"unknown command '{cmd}'; run: forge help")
    return handlers[cmd](rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
