#!/usr/bin/env python3
"""Side-by-side runtime for behavioral evals: legacy and modernized apps, each on its own
identically seeded data, described by forge/env/env.json (written by the env-provisioner agent).

  env.py up        docker compose up -d --build, then wait for both health checks
  env.py reset     recreate the data services so mutating eval cases start from the same seed
  env.py status    containers + health of both apps
  env.py down      docker compose down -v
  env.py urls      print shell exports (FORGE_LEGACY_URL / FORGE_NEW_URL)

forge/env/env.json:
  {"compose": "forge/env/docker-compose.yml", "project": "forge-<name>",
   "legacy": {"url": "http://localhost:18080", "health": "/"},
   "new":    {"url": "http://localhost:28080", "health": "/health"},
   "data_services": ["db-legacy", "db-new"], "health_timeout_seconds": 180,
   "services": {"patient-service": {"legacy": "http://localhost:18081", "new": "http://localhost:28081"}}}
  "services" is optional: per-service URLs for eval cases with "service": "<name>" (multi-service systems).
"""
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from forgelib import forge, now, read_json, workspace, write_json


def cfg():
    c = read_json(forge() / "env" / "env.json")
    if not c:
        sys.exit("forge/env/env.json missing: run /migration-forge:env (env-provisioner writes it)")
    return c


def compose(c, *args):
    if not shutil.which("docker"):
        sys.exit("docker not found: install Docker Desktop / Rancher Desktop / docker engine")
    cmd = ["docker", "compose", "-p", c.get("project", "forge"), "-f", str(workspace() / c["compose"]), *args]
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode


def healthy(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except (urllib.error.URLError, OSError):
        return False


def wait(c):
    deadline = time.time() + c.get("health_timeout_seconds", 180)
    targets = {k: c[k]["url"].rstrip("/") + c[k].get("health", "/") for k in ("legacy", "new")}
    up = {}
    while time.time() < deadline:
        up = {k: healthy(u) for k, u in targets.items()}
        if all(up.values()):
            break
        time.sleep(3)
    st = {"checked_at": now(), "healthy": up, "targets": targets}
    write_json(forge() / "env" / "status.json", st)
    for k, ok in up.items():
        print(f"{'UP  ' if ok else 'DOWN'} {k:<7} {targets[k]}")
    return all(up.values())


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    c = cfg()
    if cmd == "up":
        rc = compose(c, "up", "-d", "--build")
        sys.exit(rc or (0 if wait(c) else 2))
    if cmd == "reset":
        svcs = c.get("data_services", [])
        if not svcs:
            sys.exit("no data_services declared in env.json")
        compose(c, "rm", "-sfv", *svcs)
        rc = compose(c, "up", "-d", *svcs)
        sys.exit(rc or (0 if wait(c) else 2))
    if cmd == "down":
        sys.exit(compose(c, "down", "-v"))
    if cmd == "status":
        compose(c, "ps")
        sys.exit(0 if wait(dict(c, health_timeout_seconds=1)) else 2)
    if cmd == "urls":
        print(f"export FORGE_LEGACY_URL={c['legacy']['url']}\nexport FORGE_NEW_URL={c['new']['url']}")
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
