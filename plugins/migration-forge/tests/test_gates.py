"""Regression tests for the gate scripts (stdlib only; no Docker, no network beyond 127.0.0.1).

  cd plugins/migration-forge && python -m unittest discover -s tests -v

All PII/secret values below are synthetic test data (pii-allow: synthetic test fixtures).
"""
import http.server
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="forge-test-"))
os.environ["FORGE_HOME"] = str(TMP / "home")  # keep sonar/CA caches out of the real home
sys.path.insert(0, str(SCRIPTS))
import expect as X  # noqa: E402
import pii_scan  # noqa: E402
import score  # noqa: E402
import scanners  # noqa: E402
import sonar  # noqa: E402
from forgelib import load_gates  # noqa: E402


def workspace(name, **state):
    ws = TMP / name
    (ws / "forge").mkdir(parents=True)
    (ws / "forge" / "state.json").write_text(json.dumps(dict({"name": "t", "phase": "gate", "iteration": 0}, **state)))
    return ws


def py(script, *args, cwd, stdin=None):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd, input=stdin,
                          capture_output=True, text=True, env=dict(os.environ, EVAL_FORGE_AUTO_APPROVE="0"))


class Pii(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = pii_scan.config()

        def scan(name, files):
            d = TMP / "pii" / name
            d.mkdir(parents=True)
            for f, text in files.items():
                (d / f).write_text(text)
            return pii_scan.scan(d, cfg)

        cls.fp = scan("fp", {"Fp.java": "\n".join([
            'log.info("Sending reminder email to patient");',
            'logger.debug("card scanner started");',
            'String pwdSelector = "#pwd-input";',
            'String card = "4111 1111 1111 1111";            // published Visa test number',
            'String from = "alerts@example.com";',
            'String tokenType = "Bearer";']),
            "app.properties": "jwt.token.expiry=3600\npassword.min-length=12\n"})
        cls.tp = scan("tp", {"Tp.py": "\n".join([
            'logging.info("Created patient %s ssn=%s", d.get("name"), d.get("ssn"))',
            'print(f"patient {p.email}")',
            'log.info("user {} logged in", user.getEmail())',
            'card = "4539148803430007"',
            'sender = "alerts@notexample.com"',
            'uid = "2345 6789 0124"',
            'ssn = "123-45-6789"',
            'db_password = "S3cr3tPass"',
            'fixture_ssn = "234-56-7890"  # pii-allow: synthetic fixture for the masking test'])})

    def test_no_false_positives(self):
        self.assertEqual((len(self.fp["pii"]), len(self.fp["logs"]), len(self.fp["creds"])), (0, 0, 0),
                         [f["msg"] for f in self.fp["pii"] + self.fp["logs"] + self.fp["creds"]])

    def test_real_findings_still_caught(self):
        rules = sorted(f["rule"] for f in self.tp["pii"])
        self.assertEqual(rules, ["aadhaar", "credit_card", "email", "ssn"])
        self.assertEqual(len(self.tp["logs"]), 3)
        self.assertEqual([f["msg"].split(" =")[0] for f in self.tp["creds"]], ["db_password"])

    def test_inline_allow_is_counted_not_hidden(self):
        self.assertEqual([f["rule"] for f in self.tp["allowed"]], ["pii-allowed:ssn"])
        self.assertIn("synthetic fixture", self.tp["allowed"][0]["msg"])

    def test_output_is_masked(self):
        self.assertFalse(any("6789" in f["msg"] for f in self.tp["pii"]))


class Expect(unittest.TestCase):
    PATIENTS = [{"id": 1, "name": "A"}, {"id": 2, "name": "B", "ssn": "123-45-6789"}]

    def errs(self, body, json_rules):
        return X.check({"json": json_rules}, 200, body, json.dumps(body), 5)

    def test_wildcard_checks_every_element(self):
        self.assertIn("element 1", " ".join(self.errs(self.PATIENTS, {"*.ssn": {"absent": True}})))
        self.assertEqual(self.errs(self.PATIENTS, {"0.ssn": {"absent": True}}), [])  # why "0.ssn" was not enough

    def test_wildcard_on_empty_list_fails(self):
        self.assertIn("matched no elements", " ".join(self.errs([], {"*.ssn": {"absent": True}})))

    def test_status_list_and_latency(self):
        self.assertEqual(X.check({"status": [400, 404], "max_ms": 100}, 404, X.MISSING, "", 50), [])
        self.assertEqual(len(X.check({"status": 200, "max_ms": 100}, 500, X.MISSING, "", 150)), 2)


class EvalsRun(unittest.TestCase):
    """http_expect end to end against a stub service, including {{var}} chaining and per-service URLs."""

    def test_http_expect_against_service(self):
        class H(http.server.BaseHTTPRequestHandler):
            def reply(self, code, obj):
                self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps(obj).encode())

            def do_GET(self):
                self.reply(200, [{"id": 1, "name": "A"}, {"id": 7, "name": "B", "ssn": "123-45-6789"}]
                           if self.path == "/patients" else {"id": 7} if self.path == "/patients/7" else {"error": "x"})

            def do_POST(self):
                self.reply(201, {"id": 7})

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        ws = workspace("evals")
        url = f"http://127.0.0.1:{srv.server_port}"
        (ws / "forge" / "env").mkdir()
        (ws / "forge" / "env" / "env.json").write_text(json.dumps({"services": {"ps": {"legacy": url, "new": url}}}))
        (ws / "forge" / "evals").mkdir()
        case = lambda i, req, exp, **kw: dict({"id": i, "type": "http_expect", "service": "ps", "request": req, "expect": exp}, **kw)
        (ws / "forge" / "evals" / "cases.json").write_text(json.dumps({"cases": [
            case("EV-1", {"method": "POST", "path": "/patients", "body": {"name": "x"}}, {"status": 201}, save={"nid": "id"}),
            case("EV-2", {"path": "/patients/{{nid}}"}, {"json": {"id": 7}}),
            case("EV-3", {"path": "/patients"}, {"json": {"*.ssn": {"absent": True}}}),
        ]}))
        p = py("evals_run.py", cwd=ws)
        srv.shutdown(); srv.server_close()
        res = {c["id"]: c for c in json.loads((ws / "forge" / "evals" / "results.json").read_text())["cases"]}
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertTrue(res["EV-1"]["passed"] and res["EV-2"]["passed"], res)
        self.assertFalse(res["EV-3"]["passed"])
        self.assertIn("element 1", res["EV-3"]["detail"])


class Scoring(unittest.TestCase):
    def judge(self, check, metrics, **t):
        base = dict(load_gates()["checks"][check], **t)
        return score.judge(check, {"metrics": metrics}, base)

    def test_static_fails_on_unmeasured_metric_and_honours_null(self):
        ok_metrics = {"quality_gate_failed": 0, "bugs": 0, "vulnerabilities": 0, "security_hotspots": 0, "code_smells": 3,
                      "duplication_pct": 1.0, "security_rating": 1, "reliability_rating": 1, "maintainability_rating": 1}
        self.assertTrue(self.judge("static", ok_metrics)[0])  # min_coverage_pct is null: disabled
        ok, _, why = self.judge("static", {k: v for k, v in ok_metrics.items() if k != "bugs"})
        self.assertFalse(ok); self.assertIn("sonar bugs not measured", why)
        ok, _, why = self.judge("static", dict(ok_metrics, quality_gate_failed=1, quality_gate="ERROR"))
        self.assertFalse(ok); self.assertTrue(any("quality gate ERROR" in w for w in why))

    def test_pii(self):
        self.assertTrue(self.judge("pii", {"pii_findings": 0, "pii_in_logs": 0})[0])
        self.assertFalse(self.judge("pii", {"pii_findings": 0})[0])        # pii_in_logs not measured
        self.assertFalse(self.judge("pii", {"pii_findings": 2, "pii_in_logs": 0})[0])

    def test_security_fails_when_a_scanner_did_not_run(self):
        m = {"critical": 0, "high": 0, "secrets": 0, "hardcoded_credentials": 0, "scanners_ran": ["trivy"],
             "claude_security": "present", "scanner_errors": ["semgrep not installed and Docker not available"]}
        ok, _, why = self.judge("security", m)
        self.assertFalse(ok); self.assertTrue(why[0].startswith("scanner did not run"))
        self.assertFalse(self.judge("security", dict(m, scanner_errors=[], hardcoded_credentials=1))[0])
        self.assertTrue(self.judge("security", dict(m, scanner_errors=[]))[0])

    def test_cost_ledger(self):
        self.assertFalse(self.judge("cost", {"ledger": {"usd_total": 1, "calls": 1, "max_usd_per_call": 1, "unparsed": 1}})[0])
        self.assertFalse(self.judge("cost", {"ledger": {"usd_total": 30, "calls": 2, "max_usd_per_call": 20, "unparsed": 0}}, max_usd=25)[0])
        self.assertTrue(self.judge("cost", {"ledger": {"usd_total": 3, "calls": 2, "max_usd_per_call": 2, "unparsed": 0}}, max_usd=25)[0])


class Ledger(unittest.TestCase):
    def test_record_check_remaining(self):
        ws = workspace("ledger")
        (ws / "forge" / "gates.json").write_text(json.dumps({"checks": {"cost": {"max_usd": 10, "max_usd_per_call": 4}}}))
        ok = json.dumps({"type": "result", "total_cost_usd": 3.5, "usage": {"input_tokens": 10, "output_tokens": 5}})
        self.assertEqual(py("cost_estimate.py", "record-claude", cwd=ws, stdin=ok).returncode, 0)
        self.assertEqual(py("cost_estimate.py", "remaining", cwd=ws).stdout.strip(), "4.00")
        self.assertEqual(py("cost_estimate.py", "check", cwd=ws).returncode, 0)
        self.assertEqual(py("cost_estimate.py", "record-claude", cwd=ws, stdin="Error: crashed").returncode, 1)
        p = py("cost_estimate.py", "check", cwd=ws)
        self.assertEqual(p.returncode, 42, p.stdout); self.assertIn("unknown cost", p.stdout)

    def test_remaining_is_zero_when_budget_used_up(self):
        ws = workspace("ledger-spent")
        (ws / "forge" / "gates.json").write_text(json.dumps({"checks": {"cost": {"max_usd": 5, "max_usd_per_call": 4}}}))
        py("cost_estimate.py", "record-claude", cwd=ws, stdin=json.dumps({"total_cost_usd": 5}))
        self.assertEqual(py("cost_estimate.py", "remaining", cwd=ws).stdout.strip(), "0.00")


class SonarAnalysis(unittest.TestCase):
    def setUp(self):
        self.raw = TMP / "sonar-raw"
        (self.raw / "scannerwork").mkdir(parents=True, exist_ok=True)
        (self.raw / "scannerwork" / "report-task.txt").write_text("projectKey=k\nceTaskId=T1\n")
        sonar.time.sleep = lambda s: None
        self.real_api = sonar.api

    def tearDown(self):
        sonar.api = self.real_api

    def fake(self, task, latest):
        def api(base, path, auth, method="GET", data=None):
            if path.startswith("/api/ce/task"):
                return 200, {"task": task}
            if path.startswith("/api/project_analyses"):
                return 200, {"analyses": [{"key": latest}]}
            raise AssertionError(path)
        sonar.api = api

    def test_uses_this_runs_analysis(self):
        self.fake({"id": "T1", "status": "SUCCESS", "analysisId": "A1"}, "A1")
        self.assertEqual(sonar.this_analysis("b", self.raw, "k", "tok")["analysisId"], "A1")

    def test_rejects_failed_task_stale_analysis_and_missing_report(self):
        self.fake({"id": "T1", "status": "FAILED", "errorMessage": "boom"}, "A0")
        self.assertRaises(RuntimeError, sonar.this_analysis, "b", self.raw, "k", "tok")
        self.fake({"id": "T1", "status": "SUCCESS", "analysisId": "A1"}, "A0")
        self.assertRaises(RuntimeError, sonar.this_analysis, "b", self.raw, "k", "tok")
        (self.raw / "scannerwork" / "report-task.txt").unlink()
        self.assertRaises(RuntimeError, sonar.this_analysis, "b", self.raw, "k", "tok")


class Scanners(unittest.TestCase):
    def test_unavailable_scanner_is_an_error(self):
        g = load_gates()
        real = scanners.mode
        scanners.mode = lambda g, tool: None
        try:
            for fn in (scanners.semgrep, scanners.gitleaks, scanners.trivy):
                report, how, err = fn(g, TMP, TMP, 5)
                self.assertIsNone(report); self.assertIn("Docker not available", err)
        finally:
            scanners.mode = real

    def test_container_paths_are_made_relative(self):
        self.assertEqual([scanners.rel(p) for p in ("/src/app/x.py", "./.env", "lib/y.js")], ["app/x.py", ".env", "lib/y.js"])


class BaselineAndCompare(unittest.TestCase):
    def test_baseline_never_fails_and_leaves_state_alone(self):
        ws = workspace("baseline", legacy="legacy/t")
        (ws / "legacy" / "t").mkdir(parents=True)
        (ws / "legacy" / "t" / "app.py").write_text('ssn = "123-45-6789"\n')
        p = py("run_gates.py", "--baseline", "--only", "pii", cwd=ws)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        card = json.loads((ws / "forge" / "gates" / "baseline" / "scorecard.json").read_text())
        self.assertEqual(card["checks"]["pii"]["metrics"]["pii_findings"], 1)
        self.assertEqual(list(card["checks"]), ["pii"])
        self.assertEqual(json.loads((ws / "forge" / "state.json").read_text())["iteration"], 0)
        self.assertTrue((ws / "forge" / "gates" / "baseline" / "feedback.md").exists())
        # after: fixed code -> the report shows the improvement
        after = dict(card, iteration=1, checks={"pii": dict(card["checks"]["pii"], metrics={"pii_findings": 0, "pii_in_logs": 0})})
        (ws / "forge" / "gates" / "latest.json").write_text(json.dumps(after))
        out = py("gate_compare.py", cwd=ws)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("| pii | pii_findings | 1 | 0 | -1 | improved |", out.stdout)


class Guard(unittest.TestCase):
    def hook(self, ws, tool, tool_input):
        ev = json.dumps({"cwd": str(ws), "tool_name": tool, "tool_input": tool_input})
        return subprocess.run([sys.executable, str(SCRIPTS / "guard.py")], input=ev, capture_output=True, text=True)

    def test_new_human_and_script_owned_files(self):
        ws = workspace("guard")
        for f in ("forge/pii-allowlist.json", "forge/cost/ledger.jsonl", "forge/evals/results-legacy.json"):
            self.assertEqual(self.hook(ws, "Write", {"file_path": str(ws / f), "content": "{}"}).returncode, 2, f)
        self.assertEqual(self.hook(ws, "Bash", {"command": "echo x >> forge/cost/ledger.jsonl"}).returncode, 2)
        self.assertEqual(self.hook(ws, "Write", {"file_path": str(ws / "modernized" / "a.py"), "content": ""}).returncode, 0)


if __name__ == "__main__":
    unittest.main()
