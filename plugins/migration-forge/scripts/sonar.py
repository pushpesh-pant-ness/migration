#!/usr/bin/env python3
"""SonarQube for the `static` gate check: a local SonarQube Community container (bound to 127.0.0.1), the code scanned
with the sonar-scanner image, and measures read back for the exact analysis this run submitted.

  sonar.py up | down | status

The admin password is generated on first start and kept in ~/.migration-forge/sonar.json (FORGE_SONAR_ADMIN_PASSWORD
overrides); each scan uses a fresh token. Nothing secret is written to the workspace. First start needs ~4 GB RAM for
Docker and takes 2-5 minutes; on Linux/WSL set `sysctl -w vm.max_map_count=262144` if it keeps restarting.
"""
import base64
import json
import os
import pathlib
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import scanners
from forgelib import load_gates

NET, NAME = "forge-gates", "forge-sonarqube"
METRICS = "bugs,vulnerabilities,code_smells,security_hotspots,duplicated_lines_density,coverage,security_rating," \
          "reliability_rating,sqale_rating,ncloc"


def base_url(g):
    return f"http://127.0.0.1:{g['scanners']['sonar'].get('port', 9000)}"


def api(base, path, auth, method="GET", data=None):
    h = {"Authorization": "Basic " + base64.b64encode((auth if ":" in auth else auth + ":").encode()).decode()}
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, data=body, method=method, headers=h), timeout=60) as r:
            t = r.read().decode()
            return r.status, (json.loads(t) if t.strip().startswith(("{", "[")) else t)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except (urllib.error.URLError, OSError) as e:
        return None, str(e)


def docker(*args, timeout=300):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def up(g):
    """Start (or reuse) the SonarQube container and return admin credentials."""
    if not scanners.docker_ok():
        raise RuntimeError("Docker is not available: the static check runs SonarQube in a container")
    if docker("network", "inspect", NET).returncode:
        docker("network", "create", NET)
    running = docker("inspect", "-f", "{{.State.Running}}", NAME)
    if running.returncode:
        r = docker("run", "-d", "--name", NAME, "--network", NET, "-p", f"127.0.0.1:{g['scanners']['sonar'].get('port', 9000)}:9000",
                   "-e", "SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true", "-v", "forge-sonar-data:/opt/sonarqube/data",
                   "-v", "forge-sonar-ext:/opt/sonarqube/extensions", g["scanners"]["images"]["sonarqube"], timeout=1800)
        if r.returncode:
            raise RuntimeError(f"could not start SonarQube: {r.stderr.strip()[-300:]}")
    elif running.stdout.strip() != "true":
        docker("start", NAME)
    base = base_url(g)
    for _ in range(120):  # up to ~10 min on first start
        st, s = api(base, "/api/system/status", "x:")
        if st == 200 and isinstance(s, dict) and s.get("status") == "UP":
            break
        time.sleep(5)
    else:
        raise RuntimeError("SonarQube did not become UP (give Docker >= 4 GB RAM; see `docker logs forge-sonarqube`)")
    return admin(base)


def admin(base):
    f = scanners.HOME / "sonar.json"
    saved = scanners.load(f) or {}
    pw = os.environ.get("FORGE_SONAR_ADMIN_PASSWORD") or saved.get("password")
    if pw:
        st, v = api(base, "/api/authentication/validate", f"admin:{pw}")
        if st == 200 and isinstance(v, dict) and v.get("valid"):
            return f"admin:{pw}"
    new = pw or f"Fg#{secrets.token_urlsafe(18)}9a"  # meets SonarQube's length/upper/lower/digit/special rule
    st, r = api(base, "/api/users/change_password", "admin:admin", "POST",
                {"login": "admin", "previous_password": "admin", "password": new})
    if st not in (200, 204):
        raise RuntimeError(f"SonarQube admin password unknown ({st}): set FORGE_SONAR_ADMIN_PASSWORD to the current one")
    if not os.environ.get("FORGE_SONAR_ADMIN_PASSWORD"):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"password": new}), encoding="utf-8")
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    return f"admin:{new}"


def token(base, cred):
    api(base, "/api/user_tokens/revoke", cred, "POST", {"name": "migration-forge"})
    st, r = api(base, "/api/user_tokens/generate", cred, "POST", {"name": "migration-forge"})
    if st != 200 or not isinstance(r, dict):
        raise RuntimeError(f"cannot create a SonarQube token ({st}): {str(r)[:200]}")
    return r["token"]


def this_analysis(base, raw, key, tok):
    """The analysis this scan submitted. SonarQube keeps the previous analysis, so without this check a scan that failed
    (or never started) would silently report the last run's numbers."""
    rt = pathlib.Path(raw) / "scannerwork" / "report-task.txt"
    if not rt.exists():
        raise RuntimeError("the scanner did not submit an analysis (no report-task.txt; see raw/sonar-scanner.log)")
    props = dict(l.split("=", 1) for l in rt.read_text(encoding="utf-8").splitlines() if "=" in l)
    task = {}
    for _ in range(60):  # the scanner waited for the quality gate, so this normally finishes at once
        st, t = api(base, f"/api/ce/task?id={props['ceTaskId']}", tok)
        task = t.get("task", {}) if st == 200 and isinstance(t, dict) else {}
        if task.get("status") in ("SUCCESS", "FAILED", "CANCELED"):
            break
        time.sleep(5)
    if task.get("status") != "SUCCESS":
        raise RuntimeError(f"analysis task {props['ceTaskId']} ended {task.get('status') or 'unknown'}: {task.get('errorMessage', '')}")
    _, la = api(base, f"/api/project_analyses/search?project={key}&ps=1", tok)
    latest = (la.get("analyses") or [{}])[0].get("key") if isinstance(la, dict) else None
    if latest != task["analysisId"]:
        raise RuntimeError(f"latest analysis is {latest}, not this run's {task['analysisId']} (concurrent scan?)")
    return task


def java_binaries(root):
    """Compiled classes make Sonar's Java analysis precise; '.' is the fallback (works, fewer rules)."""
    found = [p.relative_to(root).as_posix() for pat in ("**/target/classes", "**/build/classes/java/main")
             for p in pathlib.Path(root).glob(pat) if p.is_dir() and "node_modules" not in p.parts]
    return ",".join(found[:20]) or "."


def scan(g, root, raw, key, timeout):
    """Scan root into project `key`; return the collected measures dict (raises RuntimeError when it can't)."""
    base = base_url(g)
    tok = token(base, up(g))
    s = g["scanners"]["sonar"]
    props = [f"-Dsonar.projectKey={key}", "-Dsonar.sources=.", "-Dsonar.working.directory=/out/scannerwork",
             "-Dsonar.qualitygate.wait=true", "-Dsonar.qualitygate.timeout=900", "-Dsonar.scm.disabled=true",
             f"-Dsonar.java.binaries={java_binaries(root)}", f"-Dsonar.exclusions={s.get('exclusions', '')}",
             *s.get("extra_args", [])]
    argv = scanners.docker_argv(g, "sonar_scanner", root, raw, props, network=NET, src_target="/usr/src",
                                env={"SONAR_HOST_URL": f"http://{NAME}:9000", "SONAR_TOKEN": tok})
    scanners.run_argv(argv, pathlib.Path(raw) / "sonar-scanner.log", timeout)  # rc ignored: a failed Sonar QG is data
    task = this_analysis(base, raw, key, tok)
    st, m = api(base, f"/api/measures/component?component={key}&metricKeys={METRICS}", tok)
    if st != 200 or not isinstance(m, dict):
        raise RuntimeError(f"no measures ({st}): {str(m)[:200]}")
    measures = {x["metric"]: x.get("value", x.get("period", {}).get("value")) for x in m["component"]["measures"]}
    _, q = api(base, f"/api/qualitygates/project_status?analysisId={task['analysisId']}", tok)
    _, iss = api(base, f"/api/issues/search?componentKeys={key}&resolved=false&severities=BLOCKER,CRITICAL,MAJOR&ps=100", tok)
    sevmap = {"BLOCKER": "critical", "CRITICAL": "high", "MAJOR": "medium"}
    issues = [{"tool": "sonar", "severity": sevmap.get(i["severity"], "low"), "file": i["component"].split(":", 1)[-1],
               "line": i.get("line"), "rule": i["rule"], "msg": i["message"][:200]}
              for i in (iss.get("issues", []) if isinstance(iss, dict) else [])]
    out = {"project_key": key, "analysis_id": task["analysisId"], "analysed_at": task.get("executedAt"),
           "dashboard": f"{base}/dashboard?id={key}", "measures": measures,
           "quality_gate": q.get("projectStatus", {}).get("status") if isinstance(q, dict) else None, "issues": issues}
    pathlib.Path(raw, "sonar.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    for k in ("sonar_scanner", "sonarqube"):
        scanners.record_version(raw, k, "docker", g)
    return out


if __name__ == "__main__":
    cmd, g = (sys.argv[1] if len(sys.argv) > 1 else "status"), load_gates()
    if cmd == "up":
        up(g)
        print(f"SonarQube ready at {base_url(g)} (admin password in {scanners.HOME / 'sonar.json'})")
    elif cmd == "down":
        sys.exit(docker("stop", NAME).returncode)
    elif cmd == "status":
        st, s = api(base_url(g), "/api/system/status", "x:")
        print(s if st == 200 else f"not running ({s})")
    else:
        sys.exit(__doc__)
