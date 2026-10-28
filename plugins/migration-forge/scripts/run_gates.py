#!/usr/bin/env python3
"""Run every gate tool against the modernized code and write a scored scorecard.

  run_gates.py [--root modernized/<name>] [--only tests,security]
  run_gates.py --baseline [--root legacy/<name>]     # score the legacy code once (static, security, pii); never fails

Writes forge/gates/iteration-N/{raw/*, scorecard.json, feedback.md} and forge/gates/latest.json
(baseline: forge/gates/baseline/, no iteration and no gate_history entry; compare with gate_compare.py).
Scanners (Semgrep, Gitleaks, Trivy, SonarQube) run locally when installed, else in Docker (scanners.py, sonar.py).
Evidence produced by agents is read, not generated, here:
  forge/evidence/claude-security.json {"critical":0,"high":0,"medium":0,"low":0,"report":"..."}  (gate skill writes it)
  analysis/<name>/VERIFICATION.md                                                   (code-modernization)
  forge/evals/results.json     {"cases":[{"id":..,"story":..,"priority":"P0","passed":true}]}
  forge/db/verify.json         (db_verify.py)
  forge/perf/k6-legacy.json + forge/perf/k6-modernized.json  (k6 --summary-export)
Exit code: 0 PASS, 2 FAIL.
"""
import argparse
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import cost_estimate
import pii_scan
import scanners
import sonar
from forgelib import forge, load_gates, now, read_json, save_state, state, workspace, write_json
from score import score

BASELINE_CHECKS = ("static", "security", "pii")  # what is meaningful to measure on legacy code

SKIP_DIRS = {"node_modules", ".git", "dist", "build", "target", ".venv", "venv", "bin", "obj", "__pycache__"}


def run(cmd, cwd, out, timeout):
    """Run a shell command, tee output to out, return (rc, text). rc=None on timeout/missing."""
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        text, rc = (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired:
        text, rc = f"TIMEOUT after {timeout}s: {cmd}", None
    pathlib.Path(out).write_text(f"$ {cmd}\n(rc={rc})\n{text}", encoding="utf-8")
    return rc, text


def has(tool):
    return shutil.which(tool) is not None


def files(root, *patterns):
    hits = []
    for pat in patterns:
        for p in glob.glob(str(pathlib.Path(root) / "**" / pat), recursive=True):
            if not SKIP_DIRS.intersection(pathlib.Path(p).relative_to(root).parts[:-1]):
                hits.append(p)
    return hits


def pkg_scripts(root):
    pj = read_json(pathlib.Path(root) / "package.json", {}) or {}
    s = pj.get("scripts", {})
    return {k: v for k, v in s.items() if "no test specified" not in v}


# ----------------------------------------------------------------- checks
def check_tests(root, raw, g):
    cmd = g["commands"].get("test")
    s = pkg_scripts(root)
    R = pathlib.Path(root)
    if not cmd:
        if "test" in s:
            cmd = "npm test --silent"
        elif any((R / f).exists() for f in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")) or files(root, "test_*.py"):
            cmd = f'"{sys.executable}" -m pytest -q --junitxml="{raw / "junit.xml"}"'
        elif (R / "pom.xml").exists():
            cmd = ("mvnw" if (R / "mvnw").exists() else "mvn") + " -q -B test"
        elif (R / "build.gradle").exists() or (R / "build.gradle.kts").exists():
            cmd = ("./gradlew" if (R / "gradlew").exists() else "gradle") + " test"
        elif files(root, "*.sln") or files(root, "*.csproj"):
            cmd = f'dotnet test --logger "junit;LogFilePath={raw / "junit.xml"}"'
        elif (R / "go.mod").exists():
            cmd = "go test ./..."
    if not cmd:
        return {"status": "skipped", "note": "no test command detected; set commands.test in forge/gates.json"}
    rc, log = run(cmd, root, raw / "tests.log", g["timeouts_seconds"].get("tests", 1800))
    if rc in (127, 9009) or re.search(r"No module named (pytest|mocha|jest)|is not recognized as an internal|command not found", log):
        return {"status": "error", "command": cmd, "evidence": ["raw/tests.log"],
                "note": "test runner not installed or not on PATH (see raw/tests.log)"}
    total = failed = 0
    reports = [str(p) for p in raw.glob("junit*.xml")] + files(root, "TEST-*.xml", "junit*.xml")
    for f in reports:
        try:
            r = ET.parse(f).getroot()
            suites = [r] if r.tag == "testsuite" else r.iter("testsuite")
            for su in suites:
                total += int(su.get("tests", 0))
                failed += int(su.get("failures", 0)) + int(su.get("errors", 0))
        except ET.ParseError:
            pass
    if not reports or total == 0:
        total, failed = None, (0 if rc == 0 else None if rc is None else max(1, failed))
    return {"status": "measured", "command": cmd, "metrics": {"rc": rc, "total": total, "failed": failed},
            "evidence": ["raw/tests.log"] + [os.path.relpath(f, root) for f in reports[:20]],
            "note": "" if reports else "no JUnit XML found; pass/fail by exit code only"}


def _overall_pct(p):
    if p.name.endswith(".info"):  # lcov
        lf = lh = 0
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("LF:"):
                lf += int(line[3:])
            elif line.startswith("LH:"):
                lh += int(line[3:])
        return 100 * lh / lf if lf else None
    if p.suffix == ".json":
        d = read_json(p)
        return d["total"]["lines"]["pct"] if "total" in d else d["totals"]["percent_covered"]
    r = ET.parse(p).getroot()
    if r.get("line-rate") is not None:  # cobertura
        return 100 * float(r.get("line-rate"))
    line = [c for c in r.findall("counter") if c.get("type") == "LINE"][0]  # jacoco
    cov, mis = int(line.get("covered")), int(line.get("missed"))
    return 100 * cov / (cov + mis)


def _diff_pct(root, raw, report, base_ref, timeout):
    """Changed-line coverage since base_ref via diff-cover (supports lcov, Cobertura, JaCoCo, Clover)."""
    if not base_ref:
        return None, "state.base_ref not set (the migrate skill records it after the init commit)"
    if not has("diff-cover"):
        return None, "diff-cover not installed (pipx install diff-cover)"
    if report.suffix == ".json":
        return None, "diff coverage needs lcov.info / Cobertura / JaCoCo XML, not a JSON summary"
    out = raw / "diff-cover.json"
    rc, log = run(f'diff-cover "{report}" --compare-branch={base_ref} --json-report "{out}"', root,
                  raw / "diff-cover.log", timeout)
    d = read_json(out, {}) or {}
    if rc not in (0, 1) or "total_percent_covered" not in d:
        return None, "diff-cover failed (see raw/diff-cover.log)"
    if not d.get("total_num_lines"):
        return None, "no coverable changed lines since base_ref"
    return round(float(d["total_percent_covered"]), 2), f"{d['total_num_lines']} changed coverable lines"


def check_coverage(root, raw, g, st):
    R = pathlib.Path(root)
    cand = [g["commands"].get("coverage_report")] if g["commands"].get("coverage_report") else []
    cand += files(root, "lcov.info", "cobertura*.xml", "coverage.xml", "jacoco.xml", "coverage-summary.json", "coverage.json")
    for c in cand:
        p = R / c if not os.path.isabs(c) else pathlib.Path(c)
        if not p.exists():
            continue
        try:
            pct = _overall_pct(p)
        except (KeyError, IndexError, ValueError, ET.ParseError, TypeError):
            continue
        if pct is None:
            continue
        shutil.copyfile(p, raw / ("coverage-" + p.name))
        diff, note = _diff_pct(root, raw, p, st.get("base_ref"), g["timeouts_seconds"]["default"])
        return {"status": "measured", "metrics": {"line_pct": round(float(pct), 2), "diff_line_pct": diff},
                "evidence": [str(p)] + (["raw/diff-cover.json"] if diff is not None else []),
                "note": "" if diff is not None else f"changed-line coverage unavailable: {note}; gated on overall"}
    return {"status": "skipped", "note": "no coverage report found; make the test command emit one"}


def check_review(ws):
    """Code review evidence written by the gate skill (built-in /code-review + architecture-critic)."""
    d = read_json(forge(ws) / "evidence" / "code-review.json")
    if not d:
        return {"status": "skipped", "note": "forge/evidence/code-review.json missing: run the review step of /migration-forge:gate"}
    m = {k: int(d.get(k, 0)) for k in ("blocking", "major", "minor")}
    m.update(reviewers=d.get("reviewers", []), base=d.get("base"),
             top=[f"{x.get('severity')}: {x.get('file')}:{x.get('line')} {x.get('summary')}"
                  for x in d.get("findings", []) if x.get("severity") in ("blocking", "major")][:10])
    return {"status": "measured", "metrics": m, "evidence": ["forge/evidence/code-review.json"]}


def _count_errors(rc, text, pattern):
    if rc is None:
        return None
    n = len(re.findall(pattern, text, re.M | re.I))
    return 0 if rc == 0 else max(1, n)


def check_lint(root, raw, g):
    cmd = g["commands"].get("lint")
    s = pkg_scripts(root)
    if not cmd:
        if "lint" in s:
            cmd = "npm run lint --silent"
        elif has("ruff") and files(root, "*.py"):
            cmd = "ruff check ."
    if not cmd:
        return {"status": "skipped", "note": "no lint command detected"}
    rc, out = run(cmd, root, raw / "lint.log", g["timeouts_seconds"]["default"])
    return {"status": "measured", "command": cmd, "metrics": {"errors": _count_errors(rc, out, r"\berror\b|^\S+:\d+:\d+: [A-Z]+\d+")},
            "evidence": ["raw/lint.log"]}


def check_typecheck(root, raw, g):
    cmd = g["commands"].get("typecheck")
    R = pathlib.Path(root)
    if not cmd:
        if "typecheck" in pkg_scripts(root):
            cmd = "npm run typecheck --silent"
        elif files(root, "tsconfig.json"):
            cmd = "npx --no-install tsc --noEmit -p ."
        elif has("mypy") and ((R / "mypy.ini").exists() or "[tool.mypy]" in ((R / "pyproject.toml").read_text(encoding="utf-8") if (R / "pyproject.toml").exists() else "")):
            cmd = "mypy ."
        elif (R / "pom.xml").exists() or (R / "build.gradle").exists() or files(root, "*.csproj") or (R / "go.mod").exists():
            return {"status": "measured", "metrics": {"errors": 0}, "note": "compiled language: type errors surface as test/build failures"}
    if not cmd:
        return {"status": "skipped", "note": "no type checker detected (dynamic language without mypy/tsc?)"}
    rc, out = run(cmd, root, raw / "typecheck.log", g["timeouts_seconds"]["default"])
    return {"status": "measured", "command": cmd, "metrics": {"errors": _count_errors(rc, out, r"error TS\d+|: error:")},
            "evidence": ["raw/typecheck.log"]}


_pii = {}


def pii_result(ws, root):
    """One PII/credential scan per gate run, shared by the security and pii checks."""
    if root not in _pii:
        _pii[root] = pii_scan.scan(root, pii_scan.config(ws))
    return _pii[root]


def check_security(ws, root, raw, g):
    sev = {"critical": 0, "high": 0, "medium": 0, "low": 0, "secrets": 0}
    licenses, findings = [], []
    ran, notes, ev, errors, how = [], [], [], [], {}
    t = g["timeouts_seconds"]["default"]

    d, how["semgrep"], err = scanners.semgrep(g, root, raw, t)
    if err:
        errors.append(err)
    else:
        for r in d.get("results", []):
            k = {"ERROR": "high", "WARNING": "medium"}.get(r.get("extra", {}).get("severity", "INFO"), "low")
            sev[k] += 1
            findings.append({"tool": "semgrep", "severity": k, "file": scanners.rel(r.get("path")),
                             "line": r.get("start", {}).get("line"), "rule": r.get("check_id", "").split(".")[-1],
                             "msg": r.get("extra", {}).get("message", "")[:200]})
        if d.get("errors"):
            notes.append(f"semgrep reported {len(d['errors'])} error(s) (unparsed files are not scanned; see raw/semgrep.json)")
        ran.append("semgrep"); ev.append("raw/semgrep.json")

    d, how["gitleaks"], err = scanners.gitleaks(g, root, raw, t)
    if err:
        errors.append(err)
    else:
        for r in d or []:
            sev["secrets"] += 1
            findings.append({"tool": "gitleaks", "severity": "critical", "file": scanners.rel(r.get("File")),
                             "line": r.get("StartLine"), "rule": r.get("RuleID"), "msg": r.get("Description", "secret detected")})
        ran.append("gitleaks"); ev.append("raw/gitleaks.json")

    d, how["trivy"], err = scanners.trivy(g, root, raw, t)
    if err:
        errors.append(err)
    else:
        seen = set()
        for res in d.get("Results", []) or []:
            target = scanners.rel(res.get("Target"))
            for v in res.get("Vulnerabilities") or []:
                key = (v.get("VulnerabilityID"), v.get("PkgName"), target)
                if key in seen:
                    continue
                seen.add(key)
                k = v.get("Severity", "LOW").lower()
                sev[k if k in sev else "low"] += 1
                if k in ("critical", "high"):
                    findings.append({"tool": "trivy", "severity": k, "file": target, "rule": v.get("VulnerabilityID"),
                                     "msg": f"{v.get('PkgName')} {v.get('InstalledVersion')} -> fix: {v.get('FixedVersion') or 'none yet'}"})
            for mc in res.get("Misconfigurations") or []:
                k = mc.get("Severity", "LOW").lower()
                sev[k if k in sev else "low"] += 1
                if k in ("critical", "high"):
                    findings.append({"tool": "trivy", "severity": k, "file": target, "rule": mc.get("ID"), "msg": mc.get("Title", "")})
            for s in res.get("Secrets") or []:
                sev["secrets"] += 1
                findings.append({"tool": "trivy", "severity": "critical", "file": target, "line": s.get("StartLine"),
                                 "rule": s.get("RuleID"), "msg": s.get("Title", "secret")})
            for lic in res.get("Licenses") or []:  # licence risk is tracked apart from vulnerability severity
                if lic.get("Severity") in ("CRITICAL", "HIGH"):
                    licenses.append(f"{lic.get('PkgName') or lic.get('FilePath')}: {lic.get('Name')} ({lic.get('Category')})")
        ran.append("trivy"); ev.append("raw/trivy.json")
    if (pathlib.Path(root) / "package-lock.json").exists() and has("npm"):
        run("npm audit --json > forge-npm-audit.json", root, raw / "npm-audit.log", t)
        p = pathlib.Path(root) / "forge-npm-audit.json"
        v = ((read_json(p, {}) or {}).get("metadata", {}) or {}).get("vulnerabilities", {})
        for k in ("critical", "high", "low"):
            sev[k] += v.get(k, 0)
        sev["medium"] += v.get("moderate", 0)
        if p.exists():
            shutil.move(str(p), raw / "npm-audit.json")
        ran.append("npm-audit")
    reqs = files(root, "requirements*.txt")
    if reqs and has("pip-audit"):
        run(f'pip-audit -r "{reqs[0]}" -f json -o "{raw / "pip-audit.json"}"', root, raw / "pip-audit.log", t)
        d = read_json(raw / "pip-audit.json", {}) or {}
        deps = d.get("dependencies", d if isinstance(d, list) else [])
        sev["high"] += sum(len(x.get("vulns", [])) for x in deps)  # pip-audit has no severity: counted as high
        ran.append("pip-audit")
    cs = read_json(raw / "claude-security.json")
    if cs:
        for k in ("critical", "high", "medium", "low"):
            sev[k] += int(cs.get(k, 0))
        ran.append("claude-security"); ev.append("raw/claude-security.json")
    creds = pii_result(ws, root)["creds"]
    findings += creds
    m = dict(sev, scanners_ran=ran, scanner_errors=errors, scanner_mode={k: v for k, v in how.items() if v},
             hardcoded_credentials=len(creds), claude_security="present" if cs else "missing",
             license_violations=len(licenses), license_findings=licenses[:50],
             license_scanned="trivy" in ran and "license" in g["scanners"]["trivy_scanners"])
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return {"status": "measured" if ran else "error", "metrics": m, "evidence": ev + ["raw/tool-versions.json"],
            "findings": sorted(findings, key=lambda f: order.get(f["severity"], 9))[:100],
            "note": "; ".join(errors + notes)}


def check_static(ws, st, root, raw, g, baseline=False):
    """SonarQube measures + its quality gate for the analysis this run submitted (separate project key for legacy)."""
    key = f"forge-{st.get('name') or 'run'}" + ("-legacy" if baseline else "")
    try:
        d = sonar.scan(g, root, raw, key, g["timeouts_seconds"].get("sonar", 1800))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        return {"status": "error", "note": f"SonarQube: {e}", "evidence": ["raw/sonar-scanner.log"]}
    ms = d["measures"]
    num = {"bugs": "bugs", "vulnerabilities": "vulnerabilities", "code_smells": "code_smells",
           "security_hotspots": "security_hotspots", "duplicated_lines_density": "duplication_pct", "coverage": "coverage_pct",
           "security_rating": "security_rating", "reliability_rating": "reliability_rating",
           "sqale_rating": "maintainability_rating", "ncloc": "ncloc"}
    m = {name: float(ms[k]) for k, name in num.items() if ms.get(k) not in (None, "")}
    if d.get("quality_gate"):
        m["quality_gate_failed"] = 1 if d["quality_gate"] == "ERROR" else 0
    m.update(quality_gate=d.get("quality_gate"), analysis_id=d["analysis_id"], dashboard=d["dashboard"])
    return {"status": "measured", "metrics": m, "evidence": ["raw/sonar.json"], "findings": d["issues"][:100]}


def check_pii(ws, root, raw):
    r = pii_result(ws, root)
    if not r["files"]:
        return {"status": "error", "note": f"PII scan found no readable files under {root}"}
    write_json(raw / "pii.json", {k: r[k] for k in ("pii", "logs", "allowed")})  # values are masked
    m = {"pii_findings": len(r["pii"]), "pii_in_logs": len(r["logs"]), "pii_allowed": len(r["allowed"]),
         "files_scanned": r["files"]}
    for t in ("ssn", "aadhaar", "pan", "credit_card", "email", "phone", "dob"):
        m[f"pii_{t}"] = sum(f["rule"] == t for f in r["pii"])
    return {"status": "measured", "metrics": m, "evidence": ["raw/pii.json"],
            "findings": (r["pii"] + r["logs"] + r["allowed"])[:100],
            "note": f"{len(r['allowed'])} finding(s) allowed inline with 'pii-allow:' - review the reasons" if r["allowed"] else ""}


def check_behavior(ws, st):
    m, ev = {}, []
    ver = ws / (st.get("analysis") or "") / "VERIFICATION.md"
    if st.get("analysis") and ver.exists():
        txt = ver.read_text(encoding="utf-8", errors="replace")
        np_ = len(re.findall(r"\bNOT PROVEN\b", txt))
        pp = len(re.findall(r"\bPARTLY PROVEN\b", txt))
        m.update(not_proven=np_, partly_proven=pp, proven=len(re.findall(r"\bPROVEN\b", txt)) - np_ - pp)
        ev.append(str(ver.relative_to(ws)))
    res = read_json(forge(ws) / "evals" / "results.json")
    if res and res.get("cases"):
        cases = res["cases"]
        m["acceptance_pass_pct"] = round(100 * sum(bool(c.get("passed")) for c in cases) / len(cases), 2)
        m["acceptance_failed"] = [c.get("id") for c in cases if not c.get("passed")][:50]
        ev.append("forge/evals/results.json")
    if not m:
        return {"status": "skipped", "note": "run /code-modernization:modernize-verify and the eval suite first"}
    return {"status": "measured", "metrics": m, "evidence": ev}


def check_database(ws, st, root, raw, g):
    if not st.get("db_migration") or st.get("has_database") is False:
        return {"status": "n/a", "note": "database-migration track off (existing DB kept as-is); enable with state.py set db_migration true"}
    v = read_json(forge(ws) / "db" / "verify.json")
    m = {}
    if v:
        m.update(row_match_pct=v.get("row_match_pct"), reversible=v.get("reversible"),
                 mismatched_tables=[t["table"] for t in v.get("tables", []) if not t.get("match")][:50])
    sql = [f for f in files(root, "*.sql") if re.search(r"migrat|changelog|flyway|db[\\/]", f, re.I)]
    if sql and g["scanners"].get("squawk_for_postgres") and "postgres" in (st.get("target") or "").lower():
        if has("squawk"):
            rc, out = run("squawk " + " ".join(f'"{f}"' for f in sql), root, raw / "squawk.log", g["timeouts_seconds"]["default"])
            m["lint_errors"] = 0 if rc == 0 else max(1, len(re.findall(r"\b(warning|error)\b", out, re.I)))
        else:
            m["lint_errors"] = None
    if m.get("row_match_pct") is None:
        return {"status": "skipped", "metrics": m, "note": "forge/db/verify.json missing: run db_verify.py compare + reversibility"}
    return {"status": "measured", "metrics": m, "evidence": ["forge/db/verify.json"]}


def check_cost(ws, st, root, raw, g):
    d = cost_estimate.estimate(ws, st, root, raw / "cost.json")
    return {"status": "measured", "metrics": d, "evidence": ["raw/cost.json"]}


def check_performance(ws):
    base = read_json(forge(ws) / "perf" / "k6-legacy.json")
    new = read_json(forge(ws) / "perf" / "k6-modernized.json")
    try:
        b = base["metrics"]["http_req_duration"]["p(95)"]
        n = new["metrics"]["http_req_duration"]["p(95)"]
    except (TypeError, KeyError):
        return {"status": "skipped", "note": "k6 summaries missing in forge/perf/"}
    return {"status": "measured", "metrics": {"p95_legacy_ms": b, "p95_new_ms": n,
                                              "p95_regression_pct": round(100 * (n - b) / b, 2) if b else 0}}


def feedback(card, path):
    """feedback.md: failing checks + top findings (file:line - rule - message), the remediation-engineer's worklist."""
    md = [f"# Gate feedback - {'baseline' if card.get('baseline') else 'iteration ' + str(card['iteration'])}: "
          f"{card['verdict']} (overall {card['overall_score']} / min {card['min_overall_score']})", ""]
    if not card["failures"]:
        md.append("**All checks passed.**")
    for f in card["failures"]:
        c = card["checks"].get(f["check"], {})
        md += [f"## {f['check']} ({'BLOCKER' if f['required'] else 'warning'})", ""] + [f"- {r}" for r in f["reasons"]]
        if c.get("findings"):
            md += ["", "Top findings (file:line - rule [severity] - message):"]
            md += [f"- {x.get('file')}:{x.get('line') or ''} - {x.get('rule')} [{x.get('severity')}] - {x.get('msg', '')}"
                   for x in c["findings"][:25]]
            if len(c["findings"]) > 25:
                md.append(f"- ... {len(c['findings']) - 25} more in scorecard.json")
        md.append("")
    path.write_text("\n".join(md) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="code root (default: state.modernized_root; with --baseline: state.legacy)")
    ap.add_argument("--only", help="comma list of checks to (re)run; others copied from previous scorecard")
    ap.add_argument("--baseline", action="store_true",
                    help="score the legacy code once for the before/after report; never fails, no iteration")
    a = ap.parse_args()
    ws, st, g = workspace(), state(), load_gates()
    default = st.get("legacy") if a.baseline else st.get("modernized_root")
    root = pathlib.Path(a.root).resolve() if a.root else ((ws / default).resolve() if default else None)
    if not root or not root.is_dir():
        sys.exit(f"code root unknown or missing ({root}): pass --root"
                 + ("" if a.baseline else " or `state.py set modernized_root '\"modernized/<dir>\"'`"))
    gdir = forge(ws) / "gates"
    prev = {} if a.baseline else (read_json(gdir / "latest.json", {}) or {})
    n = int(st.get("iteration", 0)) + (0 if a.baseline else 1)
    it = gdir / ("baseline" if a.baseline else f"iteration-{n}")
    if a.baseline and it.exists():
        shutil.rmtree(it)
    raw = it / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    cs = forge(ws) / "evidence" / "claude-security.json"  # written by the gate skill from /claude-security
    if cs.exists() and not a.baseline:
        shutil.copyfile(cs, raw / "claude-security.json")
    only = set(a.only.split(",")) if a.only else (set(BASELINE_CHECKS) if a.baseline else None)
    runners = {
        "tests": lambda: check_tests(root, raw, g),
        "coverage": lambda: check_coverage(root, raw, g, st),
        "lint": lambda: check_lint(root, raw, g),
        "typecheck": lambda: check_typecheck(root, raw, g),
        "static": lambda: check_static(ws, st, root, raw, g, a.baseline),
        "security": lambda: check_security(ws, root, raw, g),
        "pii": lambda: check_pii(ws, root, raw),
        "review": lambda: check_review(ws),
        "behavior": lambda: check_behavior(ws, st),
        "database": lambda: check_database(ws, st, root, raw, g),
        "cost": lambda: check_cost(ws, st, root, raw, g),
        "performance": lambda: check_performance(ws),
    }
    checks = {}
    for name, fn in runners.items():
        if a.baseline and name not in only:
            continue
        if only and name not in only and name in prev.get("checks", {}):
            checks[name] = dict(prev["checks"][name], note="carried over from iteration %s" % prev.get("iteration"))
            continue
        try:
            checks[name] = fn()
        except Exception as e:  # a crashing check is an error, never a pass
            checks[name] = {"status": "error", "note": f"{type(e).__name__}: {e}"}
        print(f"  {name:<12} {checks[name]['status']}", flush=True)
    card = {"iteration": n, "iteration_dir": str(it), "generated_at": now(), "root": str(root), "checks": checks}
    if a.baseline:  # score only what was measured; the verdict is informational
        card["baseline"] = True
        score(card, dict(g, checks={k: v for k, v in g["checks"].items() if k in checks}))
    else:
        score(card, g)
    card["feedback"] = str(it / "feedback.md")
    feedback(card, it / "feedback.md")
    write_json(it / "scorecard.json", card)
    if a.baseline:
        print(f"BASELINE {card['verdict']}  overall {card['overall_score']}  -> {it / 'scorecard.json'} (not enforced)")
        sys.exit(0)
    write_json(gdir / "latest.json", card)
    st["iteration"] = n
    st.setdefault("gate_history", []).append({"iteration": n, "verdict": card["verdict"], "overall": card["overall_score"]})
    save_state(st, ws)
    print(f"VERDICT {card['verdict']}  overall {card['overall_score']} (min {card['min_overall_score']})  -> {it / 'scorecard.json'}")
    for f in card["failures"]:
        print(f"  {'BLOCKER' if f['required'] else 'warn   '} {f['check']}: {'; '.join(f['reasons'])}")
    print(f"  feedback for remediation: {it / 'feedback.md'}")
    sys.exit(0 if card["verdict"] == "PASS" else 2)


if __name__ == "__main__":
    main()
