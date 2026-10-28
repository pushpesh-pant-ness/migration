#!/usr/bin/env python3
"""Local Jira-style tracker. Source of truth: forge/tracker/tracker.json.
Ticket files (forge/tracker/{epics,stories,tasks}/<ID>.md) carry YAML front matter that this
script owns, and a Markdown body that agents may edit (description, checkboxes, notes).

  tracker.py init
  tracker.py import backlog.json [--append]
  tracker.py add --type story --title "..." [--parent EPIC-001] [--priority P1] [--points 3]
                 [--labels a,b] [--blocked-by STORY-002,..] [--modules m1,m2] [--description "..."]
  tracker.py move <ID> <backlog|ready|in-progress|review|done> [--note "..."] [--force]
  tracker.py set <ID> [--title ..] [--priority P1] [--points 5] [--labels a,b] [--modules m1]
  tracker.py link <ID> --blocked-by <ID>
  tracker.py list [--type story] [--status ready]
  tracker.py next                       # unblocked tickets in priority + dependency order
  tracker.py show <ID>
  tracker.py validate                   # cycles, dangling links, missing acceptance criteria
  tracker.py board                      # re-render board.md
  tracker.py export-jira                # forge/tracker/export/jira-import.csv
"""
import argparse
import csv
import json
import pathlib
import re
import sys

from forgelib import forge, now, read_json, write_json

TYPES = {"epic": "EPIC", "story": "STORY", "task": "TASK", "bug": "BUG"}
DIRS = {"epic": "epics", "story": "stories", "task": "tasks", "bug": "tasks"}
STATUSES = ["backlog", "ready", "in-progress", "review", "done"]
PRIORITIES = ["P0", "P1", "P2", "P3"]
JIRA_PRIORITY = {"P0": "Highest", "P1": "High", "P2": "Medium", "P3": "Low"}
JIRA_TYPE = {"epic": "Epic", "story": "Story", "task": "Task", "bug": "Bug"}
FM = re.compile(r"\A---\n.*?\n---\n", re.S)


def root():
    return forge() / "tracker"


def db():
    d = read_json(root() / "tracker.json")
    if d is None:
        sys.exit("tracker not initialised: run tracker.py init")
    return d


def save(d, event=None):
    write_json(root() / "tracker.json", d)
    if event:
        with open(root() / "history.log", "a", encoding="utf-8", newline="\n") as f:
            f.write(f"{now()} {event}\n")
    render_board(d)


def ticket_path(t):
    return root() / DIRS[t["type"]] / f"{t['id']}.md"


def yaml_scalar(v):
    if isinstance(v, list):
        return "[" + ", ".join(json.dumps(x) for x in v) + "]"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(str(v))


def front_matter(t):
    keys = ["id", "type", "title", "status", "priority", "points", "parent", "labels",
            "blocked_by", "modules", "created", "updated"]
    return "---\n" + "".join(f"{k}: {yaml_scalar(t.get(k))}\n" for k in keys) + "---\n"


def default_body(t, spec):
    lines = [f"# {t['id']}: {t['title']}", ""]
    if t["type"] == "story" and spec.get("as_a"):
        lines += [f"**As a** {spec['as_a']}, **I want** {spec.get('i_want', '')}, "
                  f"**so that** {spec.get('so_that', '')}.", ""]
    if t["type"] == "epic":
        lines += ["## Goal", spec.get("goal", spec.get("description", "")), "",
                  "## Success metrics"] + [f"- {m}" for m in spec.get("success_metrics", [])] + [""]
        lines += ["## Scope", spec.get("scope", "TBD"), "", "## Out of scope", spec.get("out_of_scope", "TBD"), ""]
    else:
        lines += ["## Description", spec.get("description", ""), ""]
    if t["type"] != "epic":
        lines += ["## Acceptance criteria"] + [f"- [ ] {c}" for c in spec.get("acceptance", [])] + [""]
        dod = spec.get("dod") or [
            "Tests written first and passing (unit + acceptance)",
            "Behavior equivalence evidence linked (VERIFICATION.md or eval case)",
            "Latest gate scorecard PASS for the modules touched",
            "No new critical/high security findings",
            "Docs/ADR updated if behavior or architecture changed"]
        lines += ["## Definition of done"] + [f"- [ ] {c}" for c in dod] + [""]
    lines += ["## Notes", ""]
    return "\n".join(lines)


def write_ticket(t, body=None):
    p = ticket_path(t)
    p.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        old = p.read_text(encoding="utf-8") if p.exists() else ""
        body = FM.sub("", old, count=1) if old else default_body(t, {})
    p.write_text(front_matter(t) + body, encoding="utf-8", newline="\n")


def body_of(t):
    p = ticket_path(t)
    return FM.sub("", p.read_text(encoding="utf-8"), count=1) if p.exists() else ""


def new_ticket(d, typ, title, spec):
    pre = TYPES[typ]
    d["counters"][pre] = d["counters"].get(pre, 0) + 1
    tid = f"{pre}-{d['counters'][pre]:03d}"
    pr = spec.get("priority", "P2")
    if pr not in PRIORITIES:
        sys.exit(f"bad priority {pr}")
    t = {"id": tid, "type": typ, "title": title, "status": "backlog", "priority": pr,
         "points": spec.get("points"), "parent": spec.get("parent"),
         "labels": spec.get("labels", []), "blocked_by": spec.get("blocked_by", []),
         "modules": spec.get("modules", []), "created": now(), "updated": now()}
    d["items"][tid] = t
    write_ticket(t, default_body(t, spec))
    return t


def find_cycle(d):
    items = d["items"]
    state = {}

    def visit(n, path):
        if state.get(n) == 1:
            return path[path.index(n):] + [n]
        if state.get(n) == 2 or n not in items:
            return None
        state[n] = 1
        for m in items[n].get("blocked_by", []):
            c = visit(m, path + [n])
            if c:
                return c
        state[n] = 2
        return None

    for n in items:
        c = visit(n, [])
        if c:
            return c
    return None


def blockers_open(d, t):
    return [b for b in t.get("blocked_by", []) if d["items"].get(b, {}).get("status") != "done"]


def unchecked(text, section):
    m = re.search(rf"^## {section}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return re.findall(r"^- \[ \] (.+)$", m.group(1), re.M) if m else []


# ---------------------------------------------------------------- commands
def cmd_init(_):
    r = root()
    for sub in ["epics", "stories", "tasks", "checklists", "export"]:
        (r / sub).mkdir(parents=True, exist_ok=True)
    if not (r / "tracker.json").exists():
        save({"version": 1, "counters": {}, "items": {}}, "init")
    tpl = pathlib.Path(__file__).resolve().parent.parent / "skills" / "intake" / "assets" / "checklists"
    if tpl.is_dir():
        for f in tpl.glob("*.md"):
            dst = r / "checklists" / f.name
            if not dst.exists():
                dst.write_text(f.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    print(f"tracker ready at {r}")


def cmd_import(a):
    d = db()
    if d["items"] and not a.append:
        sys.exit("tracker already has items; pass --append to add more")
    spec = read_json(a.file)
    keyed = spec.get("stories", []) + spec.get("tasks", [])
    keys = {x["key"] for x in spec.get("epics", []) + keyed}
    dangling = [(x["key"], b) for x in keyed for b in x.get("blocked_by", []) if b not in keys and b not in d["items"]]
    if dangling:
        sys.exit(f"import rejected: unknown blocked_by keys {dangling} (nothing written)")
    cyc = find_cycle({"items": {x["key"]: {"blocked_by": x.get("blocked_by", [])} for x in keyed}})
    if cyc:
        sys.exit(f"import rejected: dependency cycle {' -> '.join(cyc)} (nothing written)")
    key2id = {}
    for e in spec.get("epics", []):
        key2id[e["key"]] = new_ticket(d, "epic", e["title"], e)["id"]
    for s in spec.get("stories", []):
        s = dict(s, parent=key2id.get(s.get("epic"), s.get("epic")))
        key2id[s["key"]] = new_ticket(d, "story", s["title"], {**s, "blocked_by": []})["id"]
    for k in spec.get("tasks", []):
        k = dict(k, parent=key2id.get(k.get("story"), k.get("story")))
        key2id[k["key"]] = new_ticket(d, k.get("type", "task"), k["title"], {**k, "blocked_by": []})["id"]
    # resolve dependency keys after every ticket exists
    for group in ("stories", "tasks"):
        for s in spec.get(group, []):
            t = d["items"][key2id[s["key"]]]
            t["blocked_by"] = [key2id.get(b, b) for b in s.get("blocked_by", [])]
            write_ticket(t)
    save(d, f"import {a.file} ({len(key2id)} items)")
    print(json.dumps(key2id, indent=2))


def cmd_add(a):
    d = db()
    spec = {"priority": a.priority, "points": a.points, "parent": a.parent,
            "labels": [x for x in (a.labels or "").split(",") if x],
            "blocked_by": [x for x in (a.blocked_by or "").split(",") if x],
            "modules": [x for x in (a.modules or "").split(",") if x],
            "description": a.description or "",
            "acceptance": a.ac or []}
    t = new_ticket(d, a.type, a.title, spec)
    if find_cycle(d):
        sys.exit("rejected: would create a dependency cycle")
    save(d, f"add {t['id']}")
    print(t["id"])


def cmd_move(a):
    d = db()
    t = d["items"].get(a.id) or sys.exit(f"no ticket {a.id}")
    if a.status not in STATUSES:
        sys.exit(f"status must be one of {STATUSES}")
    if a.status in ("in-progress", "review", "done") and not a.force:
        open_ = blockers_open(d, t)
        if open_:
            sys.exit(f"BLOCKED: {a.id} is blocked by open tickets {open_}")
    if a.status == "done" and not a.force:
        text = body_of(t)
        left = unchecked(text, "Acceptance criteria") + unchecked(text, "Definition of done")
        if left:
            sys.exit(f"REFUSED: {a.id} has {len(left)} unchecked acceptance/DoD items:\n- " + "\n- ".join(left))
        if t["type"] == "epic":
            kids = [k for k in d["items"].values() if k.get("parent") == a.id and k["status"] != "done"]
            if kids:
                sys.exit(f"REFUSED: epic has open children {[k['id'] for k in kids]}")
    old = t["status"]
    t["status"], t["updated"] = a.status, now()
    write_ticket(t)
    if a.note:
        p = ticket_path(t)
        p.write_text(p.read_text(encoding="utf-8").rstrip("\n") + f"\n- {now()} [{old} -> {a.status}] {a.note}\n",
                     encoding="utf-8", newline="\n")
    save(d, f"move {a.id} {old}->{a.status}" + (" FORCED" if a.force else ""))
    print(f"{a.id}: {old} -> {a.status}")


def cmd_link(a):
    d = db()
    t = d["items"].get(a.id) or sys.exit(f"no ticket {a.id}")
    if a.blocked_by not in d["items"]:
        sys.exit(f"no ticket {a.blocked_by}")
    if a.blocked_by not in t["blocked_by"]:
        t["blocked_by"].append(a.blocked_by)
    cyc = find_cycle(d)
    if cyc:
        sys.exit(f"rejected: cycle {' -> '.join(cyc)}")
    t["updated"] = now()
    write_ticket(t)
    save(d, f"link {a.id} blocked_by {a.blocked_by}")
    print(f"{a.id} blocked by {a.blocked_by}")


def cmd_set(a):
    d = db()
    t = d["items"].get(a.id) or sys.exit(f"no ticket {a.id}")
    changed = []
    for field in ("title", "priority", "points"):
        v = getattr(a, field)
        if v is not None:
            t[field] = v
            changed.append(field)
    if a.labels is not None:
        t["labels"] = [x for x in a.labels.split(",") if x]
        changed.append("labels")
    if a.modules is not None:
        t["modules"] = [x for x in a.modules.split(",") if x]
        changed.append("modules")
    t["updated"] = now()
    write_ticket(t)
    save(d, f"set {a.id} {','.join(changed)}")
    print(f"{a.id}: updated {', '.join(changed) or 'nothing'}")


def order_key(t):
    return (PRIORITIES.index(t["priority"]), t["id"])


def cmd_list(a):
    for t in sorted(db()["items"].values(), key=order_key):
        if (a.type and t["type"] != a.type) or (a.status and t["status"] != a.status):
            continue
        print(f"{t['id']:<10} {t['status']:<12} {t['priority']} {t['title']}"
              + (f"  (blocked by {','.join(t['blocked_by'])})" if t["blocked_by"] else ""))


def cmd_next(_):
    d = db()
    ready = [t for t in d["items"].values() if t["type"] != "epic"
             and t["status"] in ("backlog", "ready") and not blockers_open(d, t)]
    for t in sorted(ready, key=order_key):
        print(f"{t['id']}\t{t['priority']}\t{t['title']}")


def cmd_show(a):
    d = db()
    t = d["items"].get(a.id) or sys.exit(f"no ticket {a.id}")
    print(ticket_path(t).read_text(encoding="utf-8"))


def cmd_validate(_):
    d = db()
    errs, warns = [], []
    cyc = find_cycle(d)
    if cyc:
        errs.append(f"cycle: {' -> '.join(cyc)}")
    for t in d["items"].values():
        for b in t["blocked_by"]:
            if b not in d["items"]:
                errs.append(f"{t['id']}: blocked_by unknown {b}")
        if t.get("parent") and t["parent"] not in d["items"]:
            errs.append(f"{t['id']}: parent unknown {t['parent']}")
        if t["type"] == "story":
            if not t.get("parent"):
                warns.append(f"{t['id']}: story without epic")
            text = body_of(t)
            if not re.search(r"^## Acceptance criteria\n- \[[ x]\] ", text, re.M):
                errs.append(f"{t['id']}: no acceptance criteria")
        if t["type"] == "epic" and not any(k.get("parent") == t["id"] for k in d["items"].values()):
            warns.append(f"{t['id']}: epic has no children")
    for w in warns:
        print("WARN ", w)
    for e in errs:
        print("ERROR", e)
    print(f"{len(errs)} error(s), {len(warns)} warning(s)")
    sys.exit(1 if errs else 0)


def render_board(d):
    cols = {s: [] for s in STATUSES}
    for t in sorted(d["items"].values(), key=order_key):
        if t["type"] == "epic":
            continue
        tag = " ⛔" if blockers_open(d, t) and t["status"] != "done" else ""
        cols[t["status"]].append(f"- **{t['id']}** {t['priority']} {t['title']}{tag}")
    epics = [t for t in d["items"].values() if t["type"] == "epic"]
    out = [f"# Board  (rendered {now()})", "", "## Epics"]
    for e in sorted(epics, key=order_key):
        kids = [k for k in d["items"].values() if k.get("parent") == e["id"]]
        done = sum(k["status"] == "done" for k in kids)
        out.append(f"- **{e['id']}** {e['title']} — {done}/{len(kids)} done ({e['status']})")
    for s in STATUSES:
        out += ["", f"## {s.title()} ({len(cols[s])})"] + (cols[s] or ["- _empty_"])
    out += ["", "⛔ = blocked by an open ticket. Source of truth: tracker.json (edit via tracker.py only)."]
    (root() / "board.md").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def cmd_board(_):
    render_board(db())
    print(root() / "board.md")


def cmd_export(_):
    d = db()
    items = sorted(d["items"].values(), key=lambda t: (list(TYPES).index(t["type"]), t["id"]))
    max_l = max([len(t["labels"]) for t in items] + [1])
    max_b = max([len(t["blocked_by"]) for t in items] + [1])
    header = (["Issue Id", "Parent Id", "Issue Type", "Summary", "Description", "Priority", "Story Points"]
              + ["Labels"] * max_l + ["Blocked By"] * max_b + ["Local Status"])
    num = {t["id"]: str(i + 1) for i, t in enumerate(items)}  # Jira wants numeric-ish unique ids
    out = root() / "export" / "jira-import.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for t in items:
            desc = re.sub(r"^# .*\n", "", body_of(t), count=1).strip()
            w.writerow([num[t["id"]], num.get(t.get("parent") or "", ""), JIRA_TYPE[t["type"]],
                        f"[{t['id']}] {t['title']}", desc, JIRA_PRIORITY[t["priority"]], t.get("points") or ""]
                       + (t["labels"] + [""] * max_l)[:max_l]
                       + ([num.get(b, "") for b in t["blocked_by"]] + [""] * max_b)[:max_b]
                       + [t["status"]])
    print(out)
    print("Jira: System > External system import > CSV. Map 'Issue Id'->Issue ID, 'Parent Id'->Parent, "
          "each 'Labels'->Labels, each 'Blocked By'->Link \"Blocks\" (inward), 'Story Points'->Story point estimate.")


def main():
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("init")
    i = s.add_parser("import"); i.add_argument("file"); i.add_argument("--append", action="store_true")
    ad = s.add_parser("add")
    ad.add_argument("--type", choices=list(TYPES), required=True); ad.add_argument("--title", required=True)
    ad.add_argument("--parent"); ad.add_argument("--priority", default="P2", choices=PRIORITIES)
    ad.add_argument("--points", type=int); ad.add_argument("--labels"); ad.add_argument("--blocked-by")
    ad.add_argument("--modules"); ad.add_argument("--description"); ad.add_argument("--ac", action="append")
    m = s.add_parser("move"); m.add_argument("id"); m.add_argument("status")
    m.add_argument("--note"); m.add_argument("--force", action="store_true")
    se = s.add_parser("set"); se.add_argument("id"); se.add_argument("--title")
    se.add_argument("--priority", choices=PRIORITIES); se.add_argument("--points", type=int)
    se.add_argument("--labels"); se.add_argument("--modules")
    ln = s.add_parser("link"); ln.add_argument("id"); ln.add_argument("--blocked-by", required=True)
    ls = s.add_parser("list"); ls.add_argument("--type"); ls.add_argument("--status")
    s.add_parser("next")
    sh = s.add_parser("show"); sh.add_argument("id")
    s.add_parser("validate"); s.add_parser("board"); s.add_parser("export-jira")
    a = p.parse_args()
    {"init": cmd_init, "import": cmd_import, "add": cmd_add, "move": cmd_move, "set": cmd_set, "link": cmd_link,
     "list": cmd_list, "next": cmd_next, "show": cmd_show, "validate": cmd_validate,
     "board": cmd_board, "export-jira": cmd_export}[a.cmd](a)


if __name__ == "__main__":
    main()
