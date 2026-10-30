"""Tests for the safety rules: script-owned state keys, the phase machine, the remediation obligation, the guard's shell
rules, the Jenkins commit rules and the DB evidence (stdlib + sqlite3; needs git).

  cd plugins/migration-forge && python -m unittest discover -s tests -v
"""
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="forge-safety-test-"))
GIT = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
ENV = dict(os.environ, CLAUDE_CONFIG_DIR=str(TMP / "no-claude"))


def forge(*args, cwd, env=None):
    return subprocess.run([sys.executable, str(SCRIPTS / "forge.py"), *map(str, args)], cwd=cwd, capture_output=True,
                          text=True, env=dict(ENV, **(env or {})))


def git(cwd, *args):
    return subprocess.run(GIT + list(args), cwd=cwd, capture_output=True, text=True)


def commit(ws, msg="c"):
    git(ws, "add", "-A")
    return git(ws, "commit", "-qm", msg)


def head(ws):
    return git(ws, "rev-parse", "HEAD").stdout.strip()


def state(ws):
    return json.loads((ws / "forge" / "state.json").read_text())


def new_run(name, repo=None):
    ws = TMP / name
    ws.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    (ws / ".gitignore").write_text("legacy/\n")
    p = forge("state", "init", "--name", "shop", "--story", "Move the shop", *(["--repo", repo] if repo else []), cwd=ws)
    assert p.returncode == 0, p.stdout + p.stderr
    commit(ws, "init")
    return ws


def legacy_repo(name):
    repo = TMP / name
    repo.mkdir(parents=True)
    (repo / "app.js").write_text("module.exports = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    commit(repo, "legacy")
    return repo


def import_verdict(ws, name, failed=(), with_commit=True):
    gates = {f"gate{i}": {"passed": f"gate{i}" not in failed} for i in range(1, 5)}
    d = TMP / "results" / name
    d.mkdir(parents=True)
    (d / "summary.json").write_text(json.dumps({"phase": "after", "enforced": True, "all_passed": not failed,
                                                "failed_gates": list(failed), "gates": gates}))
    return forge("gate", "import", d / "summary.json", *(["--commit", head(ws)] if with_commit else []), cwd=ws)


def approve_all(ws):
    for what in ("backlog", "stack", "migration", "release"):
        assert forge("state", "approve", what, "--by", "user", cwd=ws).returncode == 0


class StateKeys(unittest.TestCase):
    def test_script_owned_keys_are_refused(self):
        ws = new_run("keys")
        for key, value in (("approvals", '{"backlog": {"by": "agent"}}'), ("phase", '"done"'), ("gate_history", "[]"),
                           ("legacy_fingerprint", "null")):
            p = forge("state", "set", key, value, cwd=ws)
            self.assertNotEqual(p.returncode, 0, key); self.assertIn("REFUSED", p.stderr)
        self.assertEqual(state(ws)["approvals"], {})
        self.assertEqual(forge("state", "set", "modernized_root", '"modernized/shop"', cwd=ws).returncode, 0)

    def test_commands_outside_a_workspace_create_nothing(self):
        d = TMP / "not-a-workspace"; d.mkdir()
        for args in (("state", "set", "x", "1"), ("state", "phase", "discover"), ("tracker", "init"), ("cost", "log")):
            p = forge(*args, cwd=d)
            self.assertNotEqual(p.returncode, 0, args); self.assertIn("no migration workspace", p.stderr)
        self.assertFalse((d / "forge").exists())


class PhaseMachine(unittest.TestCase):
    def test_no_skipping_and_build_phases_need_a_pass(self):
        ws = new_run("phases")
        approve_all(ws)
        p = forge("state", "phase", "execute", cwd=ws)
        self.assertNotEqual(p.returncode, 0); self.assertIn("skip", p.stderr)
        for ph in ("discover", "plan-stack", "plan-migration", "execute"):
            self.assertEqual(forge("state", "phase", ph, cwd=ws).returncode, 0, ph)
        p = forge("state", "phase", "verify", cwd=ws)
        self.assertNotEqual(p.returncode, 0); self.assertIn("Jenkins PASS", p.stderr)
        self.assertEqual(forge("state", "phase", "gate", cwd=ws).returncode, 0)
        self.assertEqual(state(ws)["gate_context"], "execute")
        commit(ws)
        self.assertEqual(import_verdict(ws, "phases-pass").returncode, 0)
        self.assertIn("PASSED for the current code", forge("next", cwd=ws).stdout)
        self.assertEqual(forge("state", "phase", "verify", cwd=ws).returncode, 0)
        # code changed after the PASS: harden needs a new verdict
        (ws / "app.py").write_text("x = 1\n"); commit(ws, "code")
        p = forge("state", "phase", "harden", cwd=ws)
        self.assertNotEqual(p.returncode, 0); self.assertIn("Jenkins PASS", p.stderr)
        self.assertEqual(forge("state", "phase", "gate", cwd=ws).returncode, 0)
        self.assertEqual(state(ws)["gate_context"], "verify")
        commit(ws)
        self.assertEqual(import_verdict(ws, "phases-pass2").returncode, 0)
        self.assertIn("forge state phase harden", forge("next", cwd=ws).stdout)
        self.assertEqual(forge("state", "phase", "harden", cwd=ws).returncode, 0)
        p = forge("state", "phase", "done", cwd=ws)
        self.assertNotEqual(p.returncode, 0); self.assertIn("VERIFICATION.md", p.stderr)
        ver = ws / "analysis" / "shop" / "VERIFICATION.md"; ver.parent.mkdir(parents=True)
        ver.write_text("| orders | NOT PROVEN |\n")
        self.assertIn("NOT PROVEN", forge("state", "phase", "done", cwd=ws).stderr)
        ver.write_text("| orders | PROVEN |\n")
        self.assertEqual(forge("state", "phase", "done", cwd=ws).returncode, 0)

    def test_escalation_returns_to_where_it_was(self):
        ws = new_run("escalate")
        self.assertEqual(forge("state", "phase", "gate", "--force", cwd=ws).returncode, 0)
        self.assertEqual(forge("state", "phase", "escalated", cwd=ws).returncode, 0)
        self.assertEqual(state(ws)["escalated_from"], "gate")
        self.assertEqual(forge("state", "phase", "remediate", cwd=ws).returncode, 0)
        self.assertNotIn("escalated_from", state(ws))


class RemediationObligation(unittest.TestCase):
    def test_committing_only_forge_evidence_is_not_a_fix(self):
        ws = new_run("obligation")
        forge("state", "phase", "gate", "--force", cwd=ws); commit(ws)
        self.assertEqual(import_verdict(ws, "obligation", failed=["gate1"]).returncode, 2)
        commit(ws, "forge: jenkins verdict iteration 1 FAIL")
        self.assertEqual(forge("next", cwd=ws).returncode, 3)
        (ws / "fix.py").write_text("x = 1\n"); commit(ws, "fix")
        self.assertEqual(forge("next", cwd=ws).returncode, 0)

    def test_committing_a_downloaded_result_is_not_a_fix(self):
        ws = new_run("obligation-offline")
        forge("state", "phase", "gate", "--force", cwd=ws); commit(ws)
        res = ws / "results" / "after"; res.mkdir(parents=True)
        (res / "summary.json").write_text(json.dumps({"phase": "after", "enforced": True, "all_passed": False,
                                                      "failed_gates": ["gate1"], "gates": {"gate1": {"passed": False}}}))
        self.assertEqual(forge("gate", "import", "results/after/summary.json", "--commit", head(ws), cwd=ws).returncode, 2)
        self.assertFalse(json.loads((ws / "forge" / "gates" / "latest.json").read_text())["workspace_dirty"])
        commit(ws, "forge: verdict and the downloaded result")
        self.assertEqual(forge("next", cwd=ws).returncode, 3)


class JenkinsCommit(unittest.TestCase):
    def test_pass_needs_the_commit_and_dirty_ignores_forge(self):
        ws = new_run("commit-rules")
        forge("state", "phase", "gate", "--force", cwd=ws)  # leaves forge/state.json modified, which is not code
        p = import_verdict(ws, "no-commit", with_commit=False)
        self.assertNotEqual(p.returncode, 0); self.assertIn("must name the commit", p.stderr)
        self.assertFalse((ws / "forge" / "gates" / "latest.json").exists())
        self.assertEqual(import_verdict(ws, "with-commit").returncode, 0)
        card = json.loads((ws / "forge" / "gates" / "latest.json").read_text())
        self.assertEqual((card["commit_verified"], card["workspace_dirty"]), (True, False))


class GuardShell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = legacy_repo("guard-legacy")
        cls.ws = new_run("guard-shell", cls.repo)
        (cls.ws / "scratch").mkdir()

    def decide(self, cmd):
        return forge("guard", "cmd", cmd, cwd=self.ws).returncode

    def test_blocks_changes_to_legacy_and_evidence(self):
        for cmd in ("rm -rf legacy", "Remove-Item -Recurse -Force legacy", "cd legacy/shop && rm app.js",
                    "git -C legacy/shop checkout .", "cp x.js legacy/shop/app.js", f'rm "{self.repo / "app.js"}"',
                    "echo 1 > legacy/shop/app.js", "find legacy/shop -name '*.js' -delete", "ls legacy/shop | xargs rm",
                    "Get-ChildItem legacy | Remove-Item", 'bash -c "rm -rf legacy/shop"', "cd legacy/shop; npm install",
                    "rm -rf .", "rm -rf *", "sed -i s/a/b/ forge/state.json", "cp evil.json forge/gates/latest.json",
                    "git checkout -- forge/state.json", "mv forge/tracker forge/old"):
            self.assertEqual(self.decide(cmd), 2, cmd)

    def test_asks_for_pause_inline_writes_and_remote_reversibility(self):
        for cmd in ("touch forge/PAUSE", "python -c \"open('forge/state.json','w').write('{}')\"",
                    "forge db reversibility --up a --down b --allow-remote"):
            self.assertEqual(self.decide(cmd), 3, cmd)

    def test_allows_reading_and_copying_out_of_legacy(self):
        for cmd in ("cp -r legacy/shop scratch/legacy-build", "git clone legacy/shop scratch/legacy-build2",
                    "grep -rn exports legacy/shop", "git -C legacy/shop log --oneline", "sed -n 1p legacy/shop/app.js",
                    "cat legacy/shop/app.js | tee scratch/out.txt", "git add -A && git commit -m 'forge: x'",
                    "npm test > scratch/test.log 2>&1", "rm -rf modernized/shop/node_modules",
                    "python -c \"import json; print(json.load(open('forge/state.json'))['phase'])\""):
            self.assertEqual(self.decide(cmd), 0, cmd)

    def test_hook_judges_a_write_by_the_files_workspace(self):
        ev = json.dumps({"cwd": str(TMP), "tool_name": "Write",
                         "tool_input": {"file_path": str(self.ws / "forge" / "state.json"), "content": "{}"}})
        p = subprocess.run([sys.executable, str(SCRIPTS / "guard.py")], input=ev, capture_output=True, text=True)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)


class PreCommitHook(unittest.TestCase):
    def test_hook_survives_a_moved_toolkit_and_works_in_a_worktree(self):
        repo = legacy_repo("hook-legacy")
        ws = new_run("hook-moved", repo)
        self.assertEqual(forge("install-git-hooks", cwd=ws).returncode, 0)
        hook = (ws / ".git" / "hooks" / "pre-commit").read_text()
        self.assertIn("FORGE_ROOT", hook)
        (ws / "a.md").write_text("a\n")
        self.assertEqual(commit(ws).returncode, 0)
        # a toolkit folder that is gone: a clear message, not a Python traceback
        p = subprocess.run(GIT + ["commit", "--allow-empty", "-qm", "x"], cwd=ws, capture_output=True, text=True,
                           env=dict(os.environ, FORGE_ROOT=str(TMP / "gone")))
        self.assertNotEqual(p.returncode, 0); self.assertIn("toolkit not found", p.stderr)
        wt = TMP / "hook-worktree"
        git(ws, "worktree", "add", "-q", str(wt), "-b", "forge/x")
        self.assertEqual(forge("install-git-hooks", cwd=wt).returncode, 0, "worktree: .git is a file there")


class DbEvidence(unittest.TestCase):
    def db(self, name, sql):
        path = TMP / f"{name}.db"
        con = sqlite3.connect(path)
        con.executescript(sql); con.commit(); con.close()
        return "sqlite:///" + path.as_posix()

    def test_a_dropped_column_is_not_a_match(self):
        ws = new_run("db-compare")
        src = self.db("src", "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, ssn TEXT);"
                             "INSERT INTO users VALUES (1, 'a@example.com', '000');")
        tgt = self.db("tgt", "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);"
                             "INSERT INTO users VALUES (1, 'a@example.com'); CREATE TABLE extra (x INT);")
        p = forge("db", "compare", cwd=ws, env={"FORGE_SOURCE_DB_URL": src, "FORGE_TARGET_DB_URL": tgt})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        v = json.loads((ws / "forge" / "db" / "verify.json").read_text())
        self.assertEqual((v["tables"][0]["match"], v["extra_target_tables"]), (False, ["extra"]))
        self.assertIn("ssn", v["tables"][0]["problem"])

    def test_reversibility_sees_indexes_and_refuses_remote_databases(self):
        ws = new_run("db-reverse")
        url = self.db("scratch", "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);")
        path = url[len("sqlite:///"):]
        py = f'"{pathlib.Path(sys.executable).as_posix()}" -c'
        up = f"{py} \"import sqlite3; c=sqlite3.connect('{path}'); c.execute('CREATE INDEX IF NOT EXISTS ix ON t(v)'); c.commit()\""
        down_leaky = f"{py} \"print('down forgot the index')\""
        p = forge("db", "reversibility", "--up", up, "--down", down_leaky, cwd=ws, env={"FORGE_SCRATCH_DB_URL": url})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        rep = json.loads((ws / "forge" / "db" / "verify.json").read_text())["reversibility"]
        self.assertFalse(rep["down_restores_schema"]); self.assertIn("ix", " ".join(rep["down_diff"]))
        for remote in ("postgresql://u:p@db.internal:5432/shop", "postgresql://u:p@localhost:5432/shop_prod"):
            p = forge("db", "reversibility", "--up", "true", "--down", "true", cwd=ws, env={"FORGE_SCRATCH_DB_URL": remote})
            self.assertNotEqual(p.returncode, 0, remote); self.assertIn("DISPOSABLE", p.stderr)


if __name__ == "__main__":
    unittest.main()
