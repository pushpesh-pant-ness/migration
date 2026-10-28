"""Tests for importing the Jenkins quality-gate verdict and the hooks that act on it (stdlib; needs git).

  cd plugins/migration-forge && python -m unittest discover -s tests -v
"""
import base64
import http.server
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="forge-jenkins-test-"))
GIT = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false"]


def summary(phase="after", enforced=True, failed=(), skipped=None):
    gates = {f"gate{i}": {"passed": f"gate{i}" not in failed, "metrics": {}} for i in range(1, 5)}
    s = {"phase": phase, "enforced": enforced, "all_passed": not failed, "failed_gates": list(failed), "gates": gates}
    if skipped:
        s.update(complete=False, skipped_checks=skipped)
    return s


def workspace(name):
    ws = TMP / name
    (ws / "forge").mkdir(parents=True)
    (ws / "forge" / "state.json").write_text(json.dumps({"name": "t", "phase": "gate", "iteration": 0}))
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(GIT + ["add", "-A"], cwd=ws, check=True)
    subprocess.run(GIT + ["commit", "-qm", "init"], cwd=ws, check=True)
    return ws


def results(name, summ, gate_files=None, feedback=None):
    d = TMP / "results" / name
    d.mkdir(parents=True)
    (d / "summary.json").write_text(json.dumps(summ))
    for g, body in (gate_files or {}).items():
        (d / f"{g}.json").write_text(json.dumps(body))
    if feedback:
        (d / "feedback.md").write_text(feedback)
    return d / "summary.json"


def py(script, *args, cwd, stdin=None, env=None):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], cwd=cwd, input=stdin,
                          capture_output=True, text=True, env=dict(os.environ, **(env or {})))


def head(ws):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws, capture_output=True, text=True).stdout.strip()


def latest(ws):
    return json.loads((ws / "forge" / "gates" / "latest.json").read_text())


class Import(unittest.TestCase):
    def test_pass_records_verdict_for_this_commit(self):
        ws = workspace("pass")
        p = py("jenkins_result.py", "import", results("pass", summary(), feedback="All gates passed."),
               "--commit", head(ws)[:8], "--build", "42", cwd=ws)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        card = latest(ws)
        self.assertEqual((card["verdict"], card["head"], card["commit_verified"], card["build"]), ("PASS", head(ws), True, "42"))
        st = json.loads((ws / "forge" / "state.json").read_text())
        self.assertEqual((st["iteration"], st["gate_history"][-1]["verdict"]), (1, "PASS"))
        self.assertTrue((ws / "forge" / "gates" / "iteration-1" / "feedback.md").exists())

    def test_fail_lists_the_failed_thresholds(self):
        ws = workspace("fail")
        gate1 = {"title": "Static analysis & security", "checks": [
            {"metric": "semgrep_high", "value": 2, "rule": {"max": 0}, "passed": False},
            {"metric": "sonar_bugs", "value": None, "rule": {"max": 0}, "passed": False, "missing": True},
            {"metric": "trivy_high", "value": 0, "rule": {"max": 0}, "passed": True}]}
        p = py("jenkins_result.py", "import", results("fail", summary(failed=["gate1"]), {"gate1": gate1}), cwd=ws)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        f = latest(ws)["failures"]
        self.assertEqual(f[0]["check"], "gate1")
        self.assertEqual(f[0]["reasons"], ["semgrep_high = 2 (required <= 0)", "sonar_bugs = not measured (required <= 0)"])

    def test_skipped_checks_make_it_a_fail(self):
        ws = workspace("skipped")
        p = py("jenkins_result.py", "import", results("skipped", summary(skipped={"gate1": ["sonar_bugs"]})), cwd=ws)
        self.assertEqual(p.returncode, 2)
        self.assertIn("incomplete", latest(ws)["failures"][0]["reasons"][0])

    def test_refuses_baseline_duplicate_and_other_commit(self):
        ws = workspace("refuse")
        p = py("jenkins_result.py", "import", results("base", summary(phase="before", enforced=False)), cwd=ws)
        self.assertNotEqual(p.returncode, 0); self.assertIn("baseline", p.stderr)
        p = py("jenkins_result.py", "import", results("other", summary()), "--commit", "deadbeef", cwd=ws)
        self.assertNotEqual(p.returncode, 0); self.assertIn("deadbeef", p.stderr)
        loc = results("dup", summary(failed=["gate4"]))
        self.assertEqual(py("jenkins_result.py", "import", loc, cwd=ws).returncode, 2)
        p = py("jenkins_result.py", "import", loc, cwd=ws)
        self.assertNotEqual(p.returncode, 2); self.assertIn("already imported", p.stderr)
        self.assertEqual(json.loads((ws / "forge" / "state.json").read_text())["iteration"], 1)

    def test_rejects_something_that_is_not_a_summary(self):
        ws = workspace("notsummary")
        bad = TMP / "results" / "bad.json"; bad.parent.mkdir(parents=True, exist_ok=True); bad.write_text('{"x": 1}')
        p = py("jenkins_result.py", "import", bad, cwd=ws)
        self.assertNotEqual(p.returncode, 0); self.assertIn("not a quality-gates summary", p.stderr)

    def test_jenkins_url_with_basic_auth(self):
        files = {"/job/x/1/artifact/results/after/summary.json": json.dumps(summary(failed=["gate2"])),
                 "/job/x/1/artifact/results/after/feedback.md": "## gate2\n- app.py:8 - hardcoded-credential"}
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get("Authorization"))
                body = files.get(self.path)
                self.send_response(200 if body else 404); self.end_headers()
                self.wfile.write((body or "").encode())

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        ws = workspace("url")
        url = f"http://127.0.0.1:{srv.server_port}/job/x/1/artifact/results/after/summary.json"
        p = py("jenkins_result.py", "import", url, cwd=ws, env={"JENKINS_USER": "u", "JENKINS_TOKEN": "t"})
        srv.shutdown(); srv.server_close()
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(seen[0], "Basic " + base64.b64encode(b"u:t").decode())
        self.assertIn("hardcoded-credential", (ws / "forge" / "gates" / "iteration-1" / "feedback.md").read_text())
        self.assertNotIn("u:t", json.dumps(latest(ws)))  # credentials are never stored


class StopHook(unittest.TestCase):
    def hook(self, ws):
        return py("stop_gate.py", cwd=ws, stdin=json.dumps({"cwd": str(ws), "stop_hook_active": False}))

    def test_blocks_on_fail_until_a_fix_is_committed(self):
        ws = workspace("stop")
        py("jenkins_result.py", "import", results("stop", summary(failed=["gate1"])), cwd=ws)
        self.assertIn('"decision": "block"', self.hook(ws).stdout)
        (ws / "fix.py").write_text("x = 1\n")
        subprocess.run(GIT + ["add", "fix.py"], cwd=ws, check=True)
        subprocess.run(GIT + ["commit", "-qm", "fix"], cwd=ws, check=True)
        self.assertEqual(self.hook(ws).stdout.strip(), "")  # waiting for Jenkins on the new commit


class Guard(unittest.TestCase):
    def test_verdicts_and_settings_are_protected(self):
        ws = workspace("guard")
        for f in ("forge/gates/latest.json", "forge/gates/iteration-1/verdict.json", "forge/settings.json"):
            ev = json.dumps({"cwd": str(ws), "tool_name": "Write", "tool_input": {"file_path": str(ws / f), "content": "{}"}})
            self.assertEqual(py("guard.py", cwd=ws, stdin=ev).returncode, 2, f)
        ev = json.dumps({"cwd": str(ws), "tool_name": "Write", "tool_input": {"file_path": str(ws / "modernized" / "a.py"), "content": ""}})
        self.assertEqual(py("guard.py", cwd=ws, stdin=ev).returncode, 0)


if __name__ == "__main__":
    unittest.main()
