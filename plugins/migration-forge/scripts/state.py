#!/usr/bin/env python3
"""Run state for a migration: forge/state.json.

  state.py init --name shop --repo ../legacy-shop --story story.md [--target "react+nestjs+postgres"] [--with-db]
      --with-db turns on the optional database-migration track (schema/data/engine changes + DB evidence).
      Off by default: the existing database is kept as-is. Toggle later: state.py set db_migration true
      init also links legacy/<name> to the repo (read-only by rule) and records its fingerprint.
  state.py phase <phase> [--force]       # move the pipeline pointer
      Refused when an approval is missing, when it would skip a phase, and for verify/harden/done without a
      commit-verified Jenkins PASS for the current code (done also needs a VERIFICATION.md with nothing NOT PROVEN).
      gate/remediate remember which build phase (execute, verify, harden) they are checking: state.gate_context.
  state.py approve <backlog|stack|migration|release> --by "<name>"
      With approvals.require_tty in settings, only a human at an interactive terminal can approve.
  state.py set <key> <json-value> [--force]   # e.g. set modernized_root '"modernized/shop"'
      Keys the scripts own (approvals, phase, gate history, fingerprint, ...) are refused without --force.
  state.py link                          # (re)create legacy/<name> here, e.g. in a git worktree
  state.py show
"""
import argparse
import json
import pathlib
import shutil
import sys

from forgelib import (FORGE_DIR, PLUGIN_ROOT, link_dir, load_settings, now, read_json, save_state, state,
                      tree_fingerprint, verdict_covers_code, workspace)

PHASES = ["intake", "discover", "plan-stack", "plan-migration", "execute", "gate",
          "remediate", "verify", "harden", "done", "escalated"]
APPROVALS = ["backlog", "stack", "migration", "release"]
# A phase may start only after these approvals exist (human checkpoints).
REQUIRES = {"discover": ["backlog"], "plan-migration": ["backlog", "stack"],
            "execute": ["backlog", "stack", "migration"], "done": ["release"]}
BUILD = ("execute", "verify", "harden")  # phases whose commit goes to the Jenkins gate
LOOP = ("gate", "remediate")
# The only forward move from each phase (going back is always allowed). The gate loop returns to its build phase.
SUCC = {"intake": "discover", "discover": "plan-stack", "plan-stack": "plan-migration", "plan-migration": "execute",
        "execute": "verify", "verify": "harden", "harden": "done"}
NEEDS_PASS = ("verify", "harden", "done")
# Keys the scripts own: approvals are a human checkpoint (`approve`), the phase has its checks (`phase`), and the rest is
# evidence the gate, the remediation budget and the legacy fingerprint rely on.
PROTECTED = {"approvals", "phase", "history", "gate_history", "iteration", "gate_context", "escalated_from",
             "legacy_fingerprint", "repo", "legacy", "name", "started_at", "updated_at"}
# Written into a new workspace, so any agent that opens it (most read AGENTS.md) finds the toolkit and the rules.
WORKSPACE_AGENTS = r"""# Migration Forge workspace: {name}

This folder is a Migration Forge run. Toolkit: `{root}` when the run started. If it moved (a new plugin version, for
example), use `$FORGE_ROOT` (in Claude Code: `${{CLAUDE_PLUGIN_ROOT}}`) and re-run `forge install-git-hooks`.

- `forge` = `"{root}/bin/forge"` (Windows cmd/PowerShell: `"{root}\bin\forge.cmd"`).
- Start or resume by following `{root}/skills/migrate/SKILL.md`. `forge brief` and `forge next` say where the run stands.
- Rules: `{root}/AGENTS.md`. Never write into `legacy/`. Only `forge` writes the evidence in `forge/`.
  Run `forge next` before ending a turn: exit 3 means a failing verdict must be remediated first.
"""


def cmd_init(a):
    ws = pathlib.Path.cwd()
    fd = ws / FORGE_DIR
    if (fd / "state.json").exists() and not a.force:
        sys.exit("forge/state.json already exists (use --force to re-init)")
    for sub in ["tracker", "gates", "decisions", "db"]:
        (fd / sub).mkdir(parents=True, exist_ok=True)
    story_dst = fd / "story.md"
    if a.story and pathlib.Path(a.story).is_file():
        shutil.copyfile(a.story, story_dst)
    elif a.story:
        story_dst.write_text(a.story + "\n", encoding="utf-8")
    st = {"name": a.name, "repo": str(pathlib.Path(a.repo).resolve()) if a.repo else None,
          "legacy": f"legacy/{a.name}", "analysis": f"analysis/{a.name}",
          "modernized_root": None, "target": a.target, "db_migration": a.with_db, "phase": "intake",
          "approvals": {}, "iteration": 0, "started_at": now(), "history": []}
    if st["repo"]:
        st["legacy_fingerprint"] = tree_fingerprint(st["repo"])
    save_state(st, ws)
    if not (ws / "AGENTS.md").exists():
        (ws / "AGENTS.md").write_text(WORKSPACE_AGENTS.format(name=a.name, root=PLUGIN_ROOT), encoding="utf-8", newline="\n")
    print(json.dumps(st, indent=2))
    if st["repo"]:
        link_legacy(ws, st)


def link_legacy(ws, st):
    link = ws / st["legacy"]
    if not pathlib.Path(st["repo"]).is_dir():
        print(f"warning: {st['repo']} does not exist; create {link} yourself once it does", file=sys.stderr)
    elif link_dir(link, st["repo"]):
        print(f"{link} -> {st['repo']} (read-only: never write into it)")
    else:
        print(f"warning: could not link {link} to {st['repo']}; link or copy it yourself", file=sys.stderr)


def cmd_link(_):
    ws = workspace()
    st = state(ws)
    if not st.get("repo"):
        sys.exit("state has no repo to link")
    link_legacy(ws, st)


def transition_problem(ws, st, to):
    """Why moving to phase `to` is refused, or None."""
    cur = st.get("phase") or "intake"
    if cur == "escalated":
        cur = st.get("escalated_from") or "intake"
    if to in ("escalated", cur):
        return None
    if to in LOOP:
        return None if cur in BUILD + LOOP else f"the Jenkins gate follows a build phase (execute, verify, harden), not '{cur}'"
    base = (st.get("gate_context") or "execute") if cur in LOOP else cur
    if PHASES.index(to) <= PHASES.index(base):
        return None  # back to an earlier phase, or back to the build phase the gate loop was checking
    if SUCC.get(base) != to:
        return f"'{to}' would skip phases: after '{base}' comes '{SUCC.get(base)}'"
    if to in NEEDS_PASS and not verdict_covers_code(ws, read_json(ws / FORGE_DIR / "gates" / "latest.json")):
        return (f"'{to}' needs a commit-verified Jenkins PASS for the current code (forge/gates/latest.json). Commit, let "
                "Jenkins build that commit, then `forge gate import <summary.json> --commit <sha>` (the gate skill)")
    if to == "done":
        ver = ws / (st.get("analysis") or f"analysis/{st.get('name')}") / "VERIFICATION.md"
        if not ver.is_file():
            return f"'done' needs {ver} (the verify skill)"
        if "NOT PROVEN" in ver.read_text(encoding="utf-8", errors="replace"):
            return f"{ver} still has a module that is NOT PROVEN"
    return None


def cmd_phase(a):
    ws = workspace()
    st = state(ws)
    if a.phase not in PHASES:
        sys.exit(f"unknown phase {a.phase}; one of {PHASES}")
    missing = [x for x in REQUIRES.get(a.phase, []) if x not in st.get("approvals", {})]
    if missing and not a.force:
        sys.exit(f"BLOCKED: phase '{a.phase}' needs human approval(s): {', '.join(missing)}. "
                 f"Ask the user, then run: state.py approve <what> --by <name>")
    problem = transition_problem(ws, st, a.phase)
    if problem and not a.force:
        sys.exit(f"BLOCKED: {problem}.")
    cur = st.get("phase")
    src = st.get("escalated_from") if cur == "escalated" else cur
    if a.phase in LOOP and src not in LOOP:
        st["gate_context"] = src if src in BUILD else "execute"
    if a.phase == "escalated" and cur != "escalated":
        st["escalated_from"] = cur
    elif a.phase != "escalated":
        st.pop("escalated_from", None)
    st.setdefault("history", []).append({"at": now(), "from": cur, "to": a.phase, **({"forced": True} if a.force else {})})
    st["phase"] = a.phase
    save_state(st, ws)
    print(f"phase -> {a.phase}" + (f" (checking the {st['gate_context']} phase)" if a.phase in LOOP else ""))


def cmd_approve(a):
    st = state()
    if (load_settings().get("approvals") or {}).get("require_tty"):
        # Any agent runs commands without a terminal, so this leaves the approval to a human.
        if not sys.stdin.isatty():
            sys.exit("REFUSED: approvals.require_tty is on. A human runs this command in their own terminal.")
        if input(f"Approve '{a.what}' for run '{st.get('name')}'? Type the run name to confirm: ").strip() != st.get("name"):
            sys.exit("not approved")
    st.setdefault("approvals", {})[a.what] = {"by": a.by, "at": now(), "note": a.note}
    save_state(st)
    print(f"approved {a.what} by {a.by}")


def cmd_set(a):
    if a.key in PROTECTED and not a.force:
        sys.exit(f"REFUSED: '{a.key}' is owned by the scripts. Approvals: `forge state approve` after the human approves; "
                 "the phase: `forge state phase`; verdicts: `forge gate import`. --force only when the human asks.")
    st = state(workspace())
    try:
        value = json.loads(a.value)
    except ValueError:
        sys.exit(f"value must be JSON, e.g. '\"text\"', true, 3 (got {a.value!r})")
    st[a.key] = value
    save_state(st)
    print(f"{a.key} = {st[a.key]!r}")


def cmd_show(_):
    ws = workspace()
    st = read_json(ws / FORGE_DIR / "state.json")
    if not st:
        sys.exit("no forge/state.json here - start a run with the migrate skill (forge state init)")
    print(json.dumps(st, indent=2))


def main():
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    i = s.add_parser("init"); i.add_argument("--name", required=True); i.add_argument("--repo")
    i.add_argument("--story"); i.add_argument("--target"); i.add_argument("--force", action="store_true")
    i.add_argument("--with-db", action="store_true", help="enable the optional database-migration track")
    ph = s.add_parser("phase"); ph.add_argument("phase"); ph.add_argument("--force", action="store_true")
    ap = s.add_parser("approve"); ap.add_argument("what", choices=APPROVALS)
    ap.add_argument("--by", required=True); ap.add_argument("--note", default="")
    st = s.add_parser("set"); st.add_argument("key"); st.add_argument("value"); st.add_argument("--force", action="store_true")
    s.add_parser("show"); s.add_parser("link")
    a = p.parse_args()
    {"init": cmd_init, "phase": cmd_phase, "approve": cmd_approve, "set": cmd_set, "show": cmd_show,
     "link": cmd_link}[a.cmd](a)


if __name__ == "__main__":
    main()
