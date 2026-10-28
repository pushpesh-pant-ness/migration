"""Security scanners for the gate: the locally installed tool when present, otherwise its Docker image, so Docker is the
only hard prerequisite (scanners.prefer in gates.json: auto | local | docker).

Each runner returns (report, how, error): the parsed JSON report (None when the tool produced none), "local"/"docker",
and an error string when the scanner could not run. A scanner that did not run is an error, never a silent pass.

Behind a TLS-inspecting proxy (e.g. Netskope) put the corporate root CA at ~/.migration-forge/corporate-ca.pem or point
FORGE_CA_CERT at it: Semgrep and Trivy containers then trust their own CA bundle plus that certificate.
"""
import json
import os
import pathlib
import shutil
import subprocess

HOME = pathlib.Path(os.environ.get("FORGE_HOME") or pathlib.Path.home() / ".migration-forge")
_docker = None


def docker_ok():
    global _docker
    if _docker is None:
        try:
            _docker = bool(shutil.which("docker")) and subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=60).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _docker = False
    return _docker


def run_argv(argv, out, timeout, cwd=None):
    """Run without a shell (paths with spaces are safe), log to out, return (rc, text); rc None on timeout/missing."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        rc, text = p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        rc, text = None, f"TIMEOUT after {timeout}s"
    except OSError as e:
        rc, text = None, str(e)
    shown = " ".join(a if " " not in a else f'"{a}"' for a in argv)
    for secret in [a.split("=", 1)[1] for a in argv if a.startswith("SONAR_TOKEN=")]:
        shown = shown.replace(secret, "***")
    pathlib.Path(out).write_text(f"$ {shown}\n(rc={rc})\n{text}", encoding="utf-8")
    return rc, text


def load(path):
    try:
        txt = pathlib.Path(path).read_text(encoding="utf-8").strip()
        return json.loads(txt) if txt else None
    except (OSError, ValueError):
        return None


def mode(g, tool):
    pref = g["scanners"].get("prefer", "auto")
    if pref != "docker" and shutil.which(tool):
        return "local"
    if pref != "local" and docker_ok():
        return "docker"
    return None


def ca_cert():
    p = pathlib.Path(os.environ.get("FORGE_CA_CERT") or HOME / "corporate-ca.pem")
    return p if p.is_file() else None


def _ca_bundle(image, key):
    """The image's own CA bundle + the corporate CA, cached under ~/.migration-forge/ca/ (never in the workspace)."""
    ca = ca_cert()
    if not ca:
        return None
    out = HOME / "ca" / f"{key}.pem"
    if not out.exists() or out.stat().st_mtime < ca.stat().st_mtime:
        base = subprocess.run(["docker", "run", "--rm", "--entrypoint", "cat", image, "/etc/ssl/certs/ca-certificates.crt"],
                              capture_output=True, text=True, timeout=600).stdout
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(base + "\n" + ca.read_text(encoding="utf-8"), encoding="utf-8")
    return out


def docker_argv(g, key, src, out_dir, args, env=None, volumes=(), network=None, src_target="/src"):
    image = g["scanners"]["images"][key]
    argv = ["docker", "run", "--rm",
            "--mount", f"type=bind,source={src},target={src_target},readonly",
            "--mount", f"type=bind,source={out_dir},target=/out"]
    bundle = _ca_bundle(image, key) if key in ("semgrep", "trivy") else None
    if bundle:
        argv += ["--mount", f"type=bind,source={bundle},target=/forge-ca.pem,readonly",
                 "-e", "SSL_CERT_FILE=/forge-ca.pem", "-e", "REQUESTS_CA_BUNDLE=/forge-ca.pem"]
    for v in volumes:
        argv += ["-v", v]
    for k, v in (env or {}).items():
        argv += ["-e", f"{k}={v}"]
    if network:
        argv += ["--network", network]
    return argv + [image] + list(args)


def image_digest(image):
    p = subprocess.run(["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
                       capture_output=True, text=True)
    return p.stdout.strip() or image


def record_version(raw, tool, how, g):
    """raw/tool-versions.json: which tool build produced the evidence (a :latest tag alone is not reproducible)."""
    f = pathlib.Path(raw) / "tool-versions.json"
    v = load(f) or {}
    if how == "docker":
        v[tool] = image_digest(g["scanners"]["images"][tool])
    elif how == "local":
        p = subprocess.run([tool, "--version"] if tool != "gitleaks" else [tool, "version"], capture_output=True, text=True)
        v[tool] = ((p.stdout or p.stderr).strip().splitlines() or ["?"])[0]
    f.write_text(json.dumps(v, indent=2), encoding="utf-8")


def _finish(raw, tool, how, rc, g, name):
    report = load(raw / name)
    record_version(raw, tool, how, g)
    return report, how, None if report is not None else f"{tool} produced no report (rc={rc}, see raw/{tool}.log)"


def semgrep(g, root, raw, timeout):
    how = mode(g, "semgrep")
    cfg = [x for c in g["scanners"]["semgrep_configs"] for x in ("--config", c)]
    common = ["--json", "--metrics=off", "--quiet"]
    if how == "local":
        rc, _ = run_argv(["semgrep", "scan", *cfg, *common, "-o", str(raw / "semgrep.json"), "."], raw / "semgrep.log", timeout, root)
    elif how == "docker":
        rc, _ = run_argv(docker_argv(g, "semgrep", root, raw, ["semgrep", "scan", *cfg, *common, "-o", "/out/semgrep.json", "/src"]),
                         raw / "semgrep.log", timeout)
    else:
        return None, None, "semgrep not installed and Docker not available"
    return _finish(raw, "semgrep", how, rc, g, "semgrep.json")


def gitleaks(g, root, raw, timeout):
    how = mode(g, "gitleaks")
    common = ["--report-format", "json", "--exit-code", "0", "--redact"]  # --redact: evidence is committed to forge/
    if how == "local":
        out = raw / "gitleaks.json"
        rc, _ = run_argv(["gitleaks", "dir", ".", *common, "--report-path", str(out), "--no-banner"], raw / "gitleaks.log", timeout, root)
        if not out.exists():  # gitleaks < 8.19 has no `dir`
            rc, _ = run_argv(["gitleaks", "detect", "--no-git", "--source", ".", *common, "--report-path", str(out), "--no-banner"],
                             raw / "gitleaks.log", timeout, root)
    elif how == "docker":
        rc, _ = run_argv(docker_argv(g, "gitleaks", root, raw, ["detect", "--no-git", "--source", "/src", *common,
                                                                "--report-path", "/out/gitleaks.json"]), raw / "gitleaks.log", timeout)
    else:
        return None, None, "gitleaks not installed and Docker not available"
    return _finish(raw, "gitleaks", how, rc, g, "gitleaks.json")


def trivy(g, root, raw, timeout):
    how = mode(g, "trivy")
    args = ["fs", "--scanners", g["scanners"]["trivy_scanners"], "--format", "json", "--quiet"]
    if how == "local":
        rc, _ = run_argv(["trivy", *args, "--output", str(raw / "trivy.json"), "."], raw / "trivy.log", timeout, root)
    elif how == "docker":
        rc, _ = run_argv(docker_argv(g, "trivy", root, raw, [*args, "--output", "/out/trivy.json", "/src"],
                                     volumes=["forge-trivy-cache:/root/.cache"]), raw / "trivy.log", timeout)
    else:
        return None, None, "trivy not installed and Docker not available"
    return _finish(raw, "trivy", how, rc, g, "trivy.json")


def rel(path):
    """Report paths from containers start with /src/; make every finding path relative to the scanned root."""
    p = str(path or "").replace("\\", "/")
    return p[5:] if p.startswith("/src/") else p[2:] if p.startswith("./") else p
