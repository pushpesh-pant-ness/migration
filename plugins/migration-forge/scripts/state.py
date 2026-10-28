#!/usr/bin/env python3
"""Run state for a migration: forge/state.json.

  state.py init --name shop --repo ../legacy-shop --story story.md [--target "react+nestjs+postgres"] [--with-db]
      --with-db turns on the optional database-migration track (schema/data/engine changes + DB gate).
      Off by default: the existing database is kept as-is. Toggle later: state.py set db_migration true
  state.py phase <phase>                 # move the pipeline pointer
  state.py approve <backlog|stack|migration|release> --by "<name>"
  state.py set <key> <json-value>        # e.g. set modernized_root '"modernized/shop"'
  state.py show
"""
import argparse
import json
import pathlib
import shutil
import sys

from forgelib import FORGE_DIR, now, read_json, save_state, state, workspace

PHASES = ["intake", "discover", "plan-stack", "plan-migration", "execute", "gate",
          "remediate", "verify", "harden", "done", "escalated"]
APPROVALS = ["backlog", "stack", "migration", "release"]
# A phase may start only after these approvals exist (human checkpoints).
REQUIRES = {"discover": ["backlog"], "plan-migration": ["backlog", "stack"],
            "execute": ["backlog", "stack", "migration"], "done": ["release"]}


def cmd_init(a):
    ws = pathlib.Path.cwd()
    fd = ws / FORGE_DIR
    if (fd / "state.json").exists() and not a.force:
        sys.exit("forge/state.json already exists (use --force to re-init)")
    for sub in ["tracker", "gates", "decisions", "db", "evals"]:
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
    save_state(st, ws)
    print(json.dumps(st, indent=2))


def cmd_phase(a):
    st = state()
    if a.phase not in PHASES:
        sys.exit(f"unknown phase {a.phase}; one of {PHASES}")
    missing = [x for x in REQUIRES.get(a.phase, []) if x not in st.get("approvals", {})]
    if missing and not a.force:
        sys.exit(f"BLOCKED: phase '{a.phase}' needs human approval(s): {', '.join(missing)}. "
                 f"Ask the user, then run: state.py approve <what> --by <name>")
    st.setdefault("history", []).append({"at": now(), "from": st.get("phase"), "to": a.phase})
    st["phase"] = a.phase
    save_state(st)
    print(f"phase -> {a.phase}")


def cmd_approve(a):
    st = state()
    st.setdefault("approvals", {})[a.what] = {"by": a.by, "at": now(), "note": a.note}
    save_state(st)
    print(f"approved {a.what} by {a.by}")


def cmd_set(a):
    st = state()
    st[a.key] = json.loads(a.value)
    save_state(st)
    print(f"{a.key} = {st[a.key]!r}")


def cmd_show(_):
    ws = workspace()
    st = read_json(ws / FORGE_DIR / "state.json")
    if not st:
        sys.exit("no forge/state.json here - run /migration-forge:migrate first")
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
    st = s.add_parser("set"); st.add_argument("key"); st.add_argument("value")
    s.add_parser("show")
    a = p.parse_args()
    {"init": cmd_init, "phase": cmd_phase, "approve": cmd_approve, "set": cmd_set, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    main()
