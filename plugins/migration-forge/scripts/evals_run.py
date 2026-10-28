#!/usr/bin/env python3
"""Run the migration eval suite forge/evals/cases.json -> forge/evals/results.json (behavior gate input).

Case types:
  command   {"command": "npx jest -t 'STORY-001'", "cwd": "modernized/shop"}       pass = exit code 0
  http_diff {"request": {"method":"GET","path":"/api/x","headers":{},"body":null},
             "ignore": ["generatedAt", "items.*.id"]}                              golden master:
            same request to $FORGE_LEGACY_URL and $FORGE_NEW_URL; status + body must match
  sql_diff  {"query": "SELECT status, count(*) FROM orders GROUP BY status ORDER BY 1",
             "target_query": "...optional, if names changed..."}                   same rows from
            $FORGE_SOURCE_DB_URL and $FORGE_TARGET_DB_URL (values normalised like db_verify)
  ui_e2e    {"spec": "checkout.spec.ts", "grep": "STORY-004", "visual": false}     Playwright spec in
            forge/evals/ui/ run against legacy first (must pass there, else the case is invalid), then
            against the new app. visual=true: screenshots recorded from legacy are the golden images.
Every case: {"id": "EV-001", "story": "STORY-001", "priority": "P0", "rule": "BR-12", "type": ...,
             "mutates": false}   mutates=true -> env.py reset before the case (same seed for both apps)
App URLs: $FORGE_LEGACY_URL / $FORGE_NEW_URL, else forge/env/env.json (see env.py).

  evals_run.py [--only EV-001,EV-007] [--timeout 300]
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from forgelib import forge, now, read_json, workspace, write_json


def strip(obj, path):
    head, _, rest = path.partition(".")
    if isinstance(obj, list) and head == "*":
        for x in obj:
            strip(x, rest) if rest else None
        if not rest:
            obj.clear()
    elif isinstance(obj, dict) and head in obj:
        if rest:
            strip(obj[head], rest)
        else:
            obj.pop(head)


def http(base, req):
    body = req.get("body")
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else (body.encode() if body else None)
    headers = {k: os.path.expandvars(str(v)) for k, v in (req.get("headers") or {}).items()}  # ${ENV} secrets
    if isinstance(body, (dict, list)):
        headers.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(base.rstrip("/") + req["path"], data=data, headers=headers,
                               method=req.get("method", "GET"))
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def app_urls():
    env = read_json(forge() / "env" / "env.json", {}) or {}
    return (os.environ.get("FORGE_LEGACY_URL") or (env.get("legacy") or {}).get("url"),
            os.environ.get("FORGE_NEW_URL") or (env.get("new") or {}).get("url"))


NO_URLS = "app URLs unknown: run /migration-forge:env (or set FORGE_LEGACY_URL / FORGE_NEW_URL)"


def run_http(c):
    old, new = app_urls()
    if not old or not new:
        return False, NO_URLS
    (s1, b1), (s2, b2) = http(old, c["request"]), http(new, c["request"])
    try:
        j1, j2 = json.loads(b1), json.loads(b2)
        for p in c.get("ignore", []):
            strip(j1, p), strip(j2, p)
        same = j1 == j2
    except json.JSONDecodeError:
        same = b1 == b2
    if s1 != s2:
        return False, f"status legacy={s1} new={s2}"
    return same, "match" if same else f"body differs (legacy {b1[:300]!r} vs new {b2[:300]!r})"


def run_sql(c):
    from db_verify import connect, norm
    try:
        a = connect("FORGE_SOURCE_DB_URL").all(c["query"])
        b = connect("FORGE_TARGET_DB_URL").all(c.get("target_query") or c["query"])
    except SystemExit as e:
        return False, str(e)
    na = [[norm(v) for v in r] for r in a]
    nb = [[norm(v) for v in r] for r in b]
    if not c.get("ordered", False):
        na, nb = sorted(na), sorted(nb)
    return na == nb, "match" if na == nb else f"{len(na)} vs {len(nb)} rows; first diff {next((x for x in zip(na, nb) if x[0] != x[1]), None)}"


def run_ui(c, ws, timeout):
    old, new = app_urls()
    if not old or not new:
        return False, NO_URLS
    ui = forge(ws) / "evals" / "ui"
    if not (ui / "node_modules" / "@playwright" / "test").exists():
        return False, "Playwright not installed: cd forge/evals/ui && npm install && npx playwright install chromium"
    base = f'npx playwright test "{c["spec"]}" --config playwright.config.ts --reporter=line'
    if c.get("grep"):
        base += f' -g "{c["grep"]}"'

    def side(url, name, extra=""):
        env = dict(os.environ, BASE_URL=url, FORGE_SIDE=name)
        try:
            p = subprocess.run(base + extra, shell=True, cwd=ui, env=env, capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8", errors="replace")
            return p.returncode, ((p.stdout or "") + (p.stderr or ""))[-800:]
        except subprocess.TimeoutExpired:
            return None, f"timeout {timeout}s"

    rc, out = side(old, "legacy", " --update-snapshots=all" if c.get("visual") else "")
    if rc != 0:
        return False, f"INVALID CASE: fails on legacy, so it proves nothing. Fix the spec. {out}"
    rc, out = side(new, "new")
    return rc == 0, "same flow passes on legacy and new" if rc == 0 else out


def run_cmd(c, ws, timeout):
    try:
        p = subprocess.run(c["command"], shell=True, cwd=ws / c.get("cwd", "."), capture_output=True,
                           text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return p.returncode == 0, ((p.stdout or "") + (p.stderr or ""))[-800:]
    except subprocess.TimeoutExpired:
        return False, f"timeout {timeout}s"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()
    ws = workspace()
    spec = read_json(forge(ws) / "evals" / "cases.json") or sys.exit("forge/evals/cases.json missing (eval-designer writes it)")
    only = set(a.only.split(",")) if a.only else None
    prev = {c["id"]: c for c in (read_json(forge(ws) / "evals" / "results.json", {}) or {}).get("cases", [])}
    out = []
    for c in spec["cases"]:
        if only and c["id"] not in only:
            if c["id"] in prev:
                out.append(prev[c["id"]])
            continue
        kind = c.get("type", "command")
        if c.get("mutates") and (forge(ws) / "env" / "env.json").exists():
            subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "env.py"), "reset"],
                           cwd=ws, capture_output=True)
        try:
            ok, detail = {"command": lambda: run_cmd(c, ws, a.timeout), "http_diff": lambda: run_http(c),
                          "sql_diff": lambda: run_sql(c), "ui_e2e": lambda: run_ui(c, ws, a.timeout)}[kind]()
        except Exception as e:  # an eval that crashes is a failed eval
            ok, detail = False, f"{type(e).__name__}: {e}"
        out.append({"id": c["id"], "story": c.get("story"), "rule": c.get("rule"), "priority": c.get("priority", "P2"),
                    "type": kind, "passed": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'} {c['id']:<8} {kind:<9} {c.get('story') or ''} {'' if ok else detail[:160]}", flush=True)
    write_json(forge(ws) / "evals" / "results.json", {"run_at": now(), "cases": out})
    failed = [c for c in out if not c["passed"]]
    print(f"{len(out) - len(failed)}/{len(out)} passed")
    sys.exit(0 if not failed else 2)


if __name__ == "__main__":
    main()
