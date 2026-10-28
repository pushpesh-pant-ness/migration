#!/usr/bin/env python3
"""Check the tools the plugin relies on and print install hints. Exit 1 if a REQUIRED tool is missing.
The quality gates and behavioral evals run in the Jenkins pipeline, so no scanner is needed here."""
import shutil
import sys

TOOLS = [
    # name, required, purpose, install hint
    ("git", True, "worktrees, diffs, the commit each Jenkins verdict is tied to", "https://git-scm.com/downloads"),
    ("docker", False, "disposable databases for db_verify.py reversibility (DB track) and running apps locally",
     "Docker Desktop / Rancher Desktop / docker engine"),
    ("squawk", False, "Postgres migration lint (DB track)", "npm i -g squawk-cli  |  pipx install squawk-cli"),
    ("infracost", False, "IaC cost for the cost report", "https://www.infracost.io/docs/  (then: infracost auth login)"),
    ("node", False, "JS/TS stacks", "https://nodejs.org (active LTS)"),
    ("npm", False, "JS tests while building", "ships with node"),
]
missing_req = 0
for name, req, purpose, hint in TOOLS:
    ok = shutil.which(name) is not None
    missing_req += (not ok) and req
    print(f"{'ok ' if ok else ('MISSING' if req else 'missing')} {name:<10} {'required' if req else 'optional'}  {purpose}"
          + ("" if ok else f"\n           install: {hint}"))
drivers = []
for mod in ("psycopg", "psycopg2", "pymysql", "mysql.connector", "pyodbc", "pymssql"):
    try:
        __import__(mod)
        drivers.append(mod)
    except ImportError:
        pass
print(f"DB drivers for db_verify.py: {', '.join(drivers) or 'none (pip install psycopg[binary] pymysql pyodbc as needed)'}")
print(f"python {sys.version.split()[0]}")
sys.exit(1 if missing_req else 0)
