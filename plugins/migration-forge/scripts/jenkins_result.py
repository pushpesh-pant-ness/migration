#!/usr/bin/env python3
"""Import the quality-gate verdict from the Jenkins pipeline. The gates and behavioral evals run there; this script
only records their result, so the phase machine, the tracker and the remediation loop can act on it.

  jenkins_result.py import [<summary.json path or URL>] [--commit <sha Jenkins built>] [--build <number or URL>]
  jenkins_result.py show

The location defaults to jenkins.results_url in settings. It is the pipeline's results/<phase>/summary.json;
feedback.md and gate1..4.json are read from the same folder when present.
Writes forge/gates/iteration-N/{summary.json, feedback.md, gate*.json, verdict.json}, forge/gates/latest.json and a
state.gate_history entry. The verdict is PASS only when the phase was enforced (not a baseline), every gate passed and
no check was skipped. It records the workspace's git HEAD: a PASS counts for that commit only. With --commit, a result
for any other commit is refused. A result that was already imported is refused too (it would skew the retry budget).
URLs: JENKINS_USER + JENKINS_TOKEN from the environment for basic auth (never stored).
Exit 0 PASS, 2 FAIL.
"""
import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

from forgelib import forge, load_settings, now, read_json, save_state, state, workspace, write_json


def fetch(loc, sibling=None):
    """Text of loc (path or URL), or of the file `sibling` in the same folder. A missing sibling is None."""
    if re.match(r"https?://", loc):
        url = loc.rsplit("/", 1)[0] + "/" + sibling if sibling else loc
        req = urllib.request.Request(url)
        user, tok = os.environ.get("JENKINS_USER"), os.environ.get("JENKINS_TOKEN")
        if user and tok:
            req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{tok}".encode()).decode())
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if sibling and e.code == 404:
                return None
            sys.exit(f"cannot fetch {url}: HTTP {e.code}" + (" (set JENKINS_USER and JENKINS_TOKEN)" if e.code in (401, 403) else ""))
        except (urllib.error.URLError, OSError) as e:
            sys.exit(f"cannot fetch {url}: {e}")
    p = pathlib.Path(loc)
    p = p.parent / sibling if sibling else p
    if p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    return None if sibling else sys.exit(f"{p} not found")


def rule_text(rule):
    if not isinstance(rule, dict):
        return str(rule)
    return " and ".join(f"{'<=' if k == 'max' else '>='} {v}" for k, v in rule.items() if k in ("max", "min")) or str(rule)


def failures(summary, gate_files):
    out = []
    for g in summary.get("failed_gates") or []:
        gj = gate_files.get(g)
        if g not in (summary.get("gates") or {}):
            reasons = ["did not run (no result in the pipeline)"]
        elif gj:
            reasons = [f"{c['metric']} = {'not measured' if c.get('missing') or c.get('value') is None else c['value']} "
                       f"(required {rule_text(c.get('rule'))})" for c in gj.get("checks", []) if c.get("passed") is False]
            reasons = reasons or ["failed (see feedback.md)"]
        else:
            reasons = ["failed (see feedback.md)"]
        out.append({"check": g, "required": True, "reasons": reasons,
                    "title": (gj or {}).get("title", "")})
    for g, skipped in (summary.get("skipped_checks") or {}).items():
        out.append({"check": g, "required": True, "reasons": [f"incomplete: skipped {', '.join(skipped)}"]})
    return out


def git(ws, *args):
    p = subprocess.run(["git", *args], cwd=ws, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def cmd_import(a):
    ws, st = workspace(), state()
    loc = a.location or (load_settings(ws).get("jenkins") or {}).get("results_url")
    if not loc:
        sys.exit("where is the Jenkins result? pass the summary.json path or URL, or set jenkins.results_url in forge/settings.json")
    text = fetch(loc)
    try:
        summary = json.loads(text)
    except ValueError:
        sys.exit(f"{loc} is not JSON (expected the pipeline's results/<phase>/summary.json)")
    if not isinstance(summary, dict) or not isinstance(summary.get("gates"), dict) or "failed_gates" not in summary:
        sys.exit(f"{loc} is not a quality-gates summary.json (needs 'gates' and 'failed_gates')")
    if not summary.get("enforced", False):
        sys.exit(f"phase '{summary.get('phase')}' is a baseline (not enforced): it records numbers, it is not a verdict. "
                 "Import an enforced phase such as 'after'.")
    head = git(ws, "rev-parse", "HEAD")
    dirty = bool(git(ws, "status", "--porcelain", "--untracked-files=no"))  # before this import writes its files
    if a.commit and head and not head.startswith(a.commit) and not a.commit.startswith(head):
        sys.exit(f"this result is for commit {a.commit}, but the workspace is at {head}: "
                 "let Jenkins build the current commit, then import that result")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    prev = read_json(forge(ws) / "gates" / "latest.json", {}) or {}
    if prev.get("summary_sha256") == sha:
        sys.exit(f"this result was already imported as iteration {prev.get('iteration')}; "
                 "run the pipeline on the new commit first")

    gate_files = {}
    n = int(st.get("iteration", 0)) + 1
    it = forge(ws) / "gates" / f"iteration-{n}"
    it.mkdir(parents=True, exist_ok=True)
    (it / "summary.json").write_text(text, encoding="utf-8")
    for g in summary["gates"]:
        t = fetch(loc, f"{g}.json")
        if t:
            (it / f"{g}.json").write_text(t, encoding="utf-8")
            try:
                gate_files[g] = json.loads(t)
            except ValueError:
                pass
    fb = fetch(loc, "feedback.md")
    if fb:
        (it / "feedback.md").write_text(fb, encoding="utf-8")

    fails = failures(summary, gate_files)
    complete = summary.get("complete", True) is not False and not summary.get("skipped_checks")
    verdict = "PASS" if not fails and summary.get("all_passed") and complete else "FAIL"
    card = {"iteration": n, "iteration_dir": str(it), "source": "jenkins", "imported_at": now(), "location": loc,
            "build": a.build, "phase": summary.get("phase"), "verdict": verdict, "overall_score": None,
            "failures": fails, "gates": {g: {"passed": v.get("passed")} for g, v in summary["gates"].items()},
            "feedback": str(it / "feedback.md") if fb else None, "head": head, "commit_verified": bool(a.commit),
            "workspace_dirty": dirty, "summary_sha256": sha}
    write_json(it / "verdict.json", card)
    write_json(forge(ws) / "gates" / "latest.json", card)
    st["iteration"] = n
    st.setdefault("gate_history", []).append({"iteration": n, "verdict": verdict, "source": "jenkins", "build": a.build,
                                              "head": head})
    save_state(st, ws)
    print(f"JENKINS VERDICT {verdict} (phase {summary.get('phase')}, iteration {n}) for commit {head or '?'}"
          + ("" if a.commit else " - not verified: pass --commit <sha Jenkins built>"))
    for f in fails:
        print(f"  BLOCKER {f['check']}: {'; '.join(f['reasons'])}")
    if dirty:
        print("  note: the workspace has uncommitted changes; this verdict does not cover them")
    if fb:
        print(f"  feedback for remediation: {it / 'feedback.md'}")
    sys.exit(0 if verdict == "PASS" else 2)


def cmd_show(_):
    card = read_json(forge() / "gates" / "latest.json") or sys.exit("no Jenkins verdict imported yet")
    print(json.dumps({k: card.get(k) for k in ("iteration", "verdict", "phase", "build", "head", "commit_verified",
                                               "failures", "feedback", "imported_at")}, indent=2))


def main():
    ap = argparse.ArgumentParser()
    s = ap.add_subparsers(dest="cmd", required=True)
    i = s.add_parser("import"); i.add_argument("location", nargs="?")
    i.add_argument("--commit", help="the commit SHA the Jenkins build tested (GIT_COMMIT in the build)")
    i.add_argument("--build", help="build number or URL, for the record")
    s.add_parser("show")
    a = ap.parse_args()
    {"import": cmd_import, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    main()
