#!/usr/bin/env python3
"""Check the tools the gates rely on and print install hints. Exit 1 if a REQUIRED tool is missing.
Docker is the one hard requirement for the gates: SonarQube always runs in it, and Semgrep/Gitleaks/Trivy run in it
whenever they are not installed locally (scripts/scanners.py)."""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scanners  # noqa: E402

TOOLS = [
    # name, required, purpose, install hint
    ("git", True, "worktrees, diffs", "https://git-scm.com/downloads"),
    ("docker", True, "SonarQube + scanner images (static/security gates) and the side-by-side legacy/new runtime (env.py)",
     "Docker Desktop / Rancher Desktop / docker engine (give it >= 4 GB RAM for SonarQube)"),
    ("semgrep", False, "SAST (security gate) - else the Docker image is used", "pipx install semgrep   |  brew install semgrep"),
    ("gitleaks", False, "secret scan (security gate) - else the Docker image is used", "brew install gitleaks  |  winget install gitleaks"),
    ("trivy", False, "deps/IaC/secret/licence scan (security gate) - else the Docker image is used", "brew install trivy  |  winget install AquaSecurity.Trivy"),
    ("npx", False, "Playwright UI parity evals (ui_e2e)", "ships with node; then in forge/evals/ui: npm install && npx playwright install chromium"),
    ("squawk", False, "Postgres migration lint", "npm i -g squawk-cli  |  pipx install squawk-cli"),
    ("pip-audit", False, "Python dependency audit", "pipx install pip-audit"),
    ("diff-cover", False, "changed-line coverage (else gate falls back to overall coverage)", "pipx install diff-cover"),
    ("infracost", False, "IaC cost (cost gate)", "https://www.infracost.io/docs/  (then: infracost auth login)"),
    ("k6", False, "performance smoke test", "https://grafana.com/docs/k6/latest/set-up/install-k6/"),
    ("node", False, "JS/TS stacks", "https://nodejs.org (active LTS)"),
    ("npm", False, "npm audit / JS tests", "ships with node"),
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
if shutil.which("docker") and not scanners.docker_ok():
    missing_req += 1
    print("MISSING docker daemon: the docker CLI is installed but the engine is not running (start Docker Desktop)")
ca = scanners.ca_cert()
print(f"corporate CA for scanner containers: {ca or 'none (only needed behind a TLS-inspecting proxy: put it at ~/.migration-forge/corporate-ca.pem)'}")
print(f"DB drivers for db_verify.py: {', '.join(drivers) or 'none (pip install psycopg[binary] pymysql pyodbc as needed)'}")
print(f"python {sys.version.split()[0]}")
sys.exit(1 if missing_req else 0)
