"""Tests for running the toolkit without any AI tool: the forge CLI, the guard's exit-code protocol, the legacy
link and fingerprint, the git pre-commit hook, TTY-only approvals and the usage ledger (stdlib; needs git).

  cd plugins/migration-forge && python -m unittest discover -s tests -v
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="forge-standalone-test-"))
GIT = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
# No Claude Code transcripts may leak into the cost tests from the machine running them.
ENV = dict(os.environ, CLAUDE_CONFIG_DIR=str(TMP / "no-claude"))


def forge(*args, cwd, stdin=""):
    return subprocess.run([sys.executable, str(SCRIPTS / "forge.py"), *map(str, args)], cwd=cwd, input=stdin,
                          capture_output=True, text=True, env=ENV)


def git(cwd, *args):
    return subprocess.run(GIT + list(args), cwd=cwd, capture_output=True, text=True)


def legacy_repo(name):
    repo = TMP / name
    repo.mkdir(parents=True)
    (repo / "app.js").write_text("module.exports = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "legacy")
    return repo


def new_run(name, repo=None):
    ws = TMP / name
    ws.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    p = forge("state", "init", "--name", "shop", "--story", "Move the shop", *(["--repo", repo] if repo else []), cwd=ws)
    assert p.returncode == 0, p.stdout + p.stderr
    return ws


def summary(failed=()):
    gates = {f"gate{i}": {"passed": f"gate{i}" not in failed, "metrics": {}} for i in range(1, 5)}
    return {"phase": "after", "enforced": True, "all_passed": not failed, "failed_gates": list(failed), "gates": gates}


class Cli(unittest.TestCase):
    def test_help_root_and_unknown(self):
        self.assertEqual(forge("help", cwd=TMP).returncode, 0)
        self.assertEqual(pathlib.Path(forge("root", cwd=TMP).stdout.strip()), SCRIPTS.parent)
        self.assertNotEqual(forge("nope", cwd=TMP).returncode, 0)

    def test_init_links_legacy_and_writes_agents_md(self):
        repo = legacy_repo("legacy-init")
        ws = new_run("init", repo)
        st = json.loads((ws / "forge" / "state.json").read_text())
        self.assertTrue(st["legacy_fingerprint"].startswith("git:"))
        self.assertEqual((ws / "legacy" / "shop").resolve(), repo.resolve())
        self.assertIn("skills/migrate/SKILL.md", (ws / "AGENTS.md").read_text())
        self.assertIn("phase=intake", forge("brief", cwd=ws).stdout)

    def test_next_requires_remediation_until_a_fix_is_committed(self):
        ws = new_run("next")
        git(ws, "add", "-A"); git(ws, "commit", "-qm", "init")
        forge("state", "phase", "gate", "--force", cwd=ws)
        res = TMP / "results-next"; res.mkdir()
        (res / "summary.json").write_text(json.dumps(summary(failed=["gate1"])))
        self.assertEqual(forge("gate", "import", res / "summary.json", cwd=ws).returncode, 2)
        p = forge("next", cwd=ws)
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr); self.assertIn("MUST CONTINUE", p.stdout)
        (ws / "fix.py").write_text("x = 1\n")
        git(ws, "add", "-A"); git(ws, "commit", "-qm", "fix")
        self.assertEqual(forge("next", cwd=ws).returncode, 0)


class GuardCli(unittest.TestCase):
    def test_exit_codes(self):
        ws = new_run("guard-cli")
        self.assertEqual(forge("guard", "path", "forge/gates/latest.json", cwd=ws).returncode, 2)
        self.assertEqual(forge("guard", "path", "legacy/shop/app.js", cwd=ws).returncode, 2)
        self.assertEqual(forge("guard", "path", "modernized/shop/app.ts", cwd=ws).returncode, 0)
        self.assertEqual(forge("guard", "cmd", "rm -rf legacy/shop", cwd=ws).returncode, 2)
        self.assertEqual(forge("guard", "cmd", 'forge state approve stack --by me', cwd=ws).returncode, 3)
        self.assertEqual(forge("guard", "cmd", 'bin/forge tracker move S-1 done --force', cwd=ws).returncode, 3)
        self.assertEqual(forge("guard", "cmd", "npm test", cwd=ws).returncode, 0)

    def test_claude_code_hook_asks_for_approvals(self):
        ws = new_run("guard-hook")
        ev = json.dumps({"cwd": str(ws), "tool_name": "Bash",
                         "tool_input": {"command": "bash forge.py state approve backlog --by me"}})
        p = subprocess.run([sys.executable, str(SCRIPTS / "guard.py")], cwd=ws, input=ev, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")


class Legacy(unittest.TestCase):
    def test_fingerprint_and_pre_commit_hook(self):
        repo = legacy_repo("legacy-hook")
        ws = new_run("hook", repo)
        self.assertEqual(forge("install-git-hooks", cwd=ws).returncode, 0)
        (repo / "build.log").write_text("untracked build output does not count\n")
        self.assertEqual(forge("guard", "legacy", cwd=ws).returncode, 0)
        git(ws, "add", "-A")
        self.assertEqual(git(ws, "commit", "-qm", "ok").returncode, 0)
        (repo / "app.js").write_text("module.exports = 2\n")
        self.assertEqual(forge("guard", "legacy", cwd=ws).returncode, 2)
        (ws / "note.md").write_text("x\n"); git(ws, "add", "-A")
        p = git(ws, "commit", "-qm", "blocked")
        self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("legacy source", p.stderr)

    def test_fingerprint_without_git(self):
        sys.path.insert(0, str(SCRIPTS))
        from forgelib import tree_fingerprint
        d = TMP / "plain-legacy"; (d / "node_modules").mkdir(parents=True)
        (d / "a.php").write_text("<?php echo 1;")
        before = tree_fingerprint(d)
        (d / "node_modules" / "x.js").write_text("ignored")
        self.assertEqual(tree_fingerprint(d), before)
        (d / "a.php").write_text("<?php echo 22;")
        self.assertNotEqual(tree_fingerprint(d), before)


class Approvals(unittest.TestCase):
    def test_require_tty_refuses_without_a_terminal(self):
        ws = new_run("tty")
        (ws / "forge" / "settings.json").write_text(json.dumps({"approvals": {"require_tty": True}}))
        p = forge("state", "approve", "backlog", "--by", "agent", cwd=ws)
        self.assertNotEqual(p.returncode, 0); self.assertIn("require_tty", p.stderr)
        self.assertEqual(json.loads((ws / "forge" / "state.json").read_text())["approvals"], {})

    def test_default_records_the_approval(self):
        ws = new_run("approve")
        self.assertEqual(forge("state", "approve", "backlog", "--by", "user", cwd=ws).returncode, 0)
        self.assertIn("backlog", json.loads((ws / "forge" / "state.json").read_text())["approvals"])


class Cost(unittest.TestCase):
    def test_usage_ledger(self):
        ws = new_run("cost")
        p = forge("cost", cwd=ws)
        self.assertEqual(p.returncode, 0, p.stderr); self.assertIn("unknown, not zero", p.stdout)
        forge("cost", "log", "--input", "1000", "--output", "200", "--cache-read", "5000", "--source", "codex", cwd=ws)
        forge("cost", "log", "--input", "10", "--output", "5", "--source", "sandbox", cwd=ws)
        res = json.loads(forge("cost", cwd=ws).stdout)
        self.assertEqual((res["tokens_total"], res["tokens"]["cache_read"]), (1215, 5000))
        self.assertEqual(res["sources"]["usage_ledger_entries"], 2)
        self.assertNotIn("tokens_note", res)


if __name__ == "__main__":
    unittest.main()
