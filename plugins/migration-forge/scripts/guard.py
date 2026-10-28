#!/usr/bin/env python3
"""PreToolUse guard (active only inside a migration workspace, i.e. forge/state.json exists).

Blocks (exit 2, reason on stderr):
  - any write into legacy/ or the original repo path (legacy code is read-only evidence)
  - hand edits of script-owned evidence: tracker.json, history.log, gate scorecards,
    db/verify.json, evals/results.json, the Claude cost ledger (cost/ledger.jsonl)
  - edits of gate thresholds (forge/gates.json) and the PII allowlist (forge/pii-allowlist.json):
    both are changed by humans, outside Claude
  - shell commands that delete/overwrite/redirect into legacy/
  - hand edits of forge/state.json (phase + approvals live there)
Asks (forces a human permission prompt, even when the session auto-approves Bash):
  - state.py approve ...    (human checkpoints must be confirmed by a human click)
  - state.py / tracker.py ... --force
"""
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forgelib import FORGE_DIR, find_workspace as find_ws, native_path, read_json  # noqa: E402

OWNED = [("tracker", "tracker.json"), ("tracker", "history.log"), ("db", "verify.json"),
         ("evals", "results.json"), ("evals", "results-legacy.json"), ("cost", "ledger.jsonl")]


def inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def block(msg):
    print(f"migration-forge guard: {msg}", file=sys.stderr)
    sys.exit(2)


def ask(msg):
    """Force an interactive permission prompt, so a human (not the model) confirms.
    EVAL_FORGE_AUTO_APPROVE=1 (set only by `claude plugin eval` case env, never by the model:
    Bash commands cannot change the hook's environment) skips the prompt for headless eval runs."""
    if os.environ.get("EVAL_FORGE_AUTO_APPROVE") == "1":
        sys.exit(0)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": f"migration-forge: {msg}"}}))
    sys.exit(0)


def main():
    try:
        ev = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)
    ws = find_ws(ev.get("cwd") or os.getcwd())
    if not ws:
        sys.exit(0)
    st = read_json(ws / FORGE_DIR / "state.json", {}) or {}
    legacy_roots = [(ws / "legacy").resolve()]
    if st.get("repo"):
        legacy_roots.append(pathlib.Path(st["repo"]).resolve())
    tool, ti = ev.get("tool_name", ""), ev.get("tool_input") or {}
    fd = (ws / FORGE_DIR).resolve()

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        raw = ti.get("file_path") or ti.get("notebook_path")
        if not raw:
            sys.exit(0)
        p = native_path(raw)
        p = (p if p.is_absolute() else ws / p).resolve()
        if any(inside(p, r) for r in legacy_roots):
            block(f"{p} is legacy source (read-only). Write new code under modernized/ instead.")
        for sub, name in OWNED:
            if p == fd / sub / name:
                block(f"{p.name} is owned by migration-forge scripts; use tracker.py / db_verify.py / evals_run.py.")
        if inside(p, fd / "gates"):
            block("gate scorecards are produced only by run_gates.py; fix the code, then re-run the gate.")
        if p == fd / "gates.json":
            block("gate thresholds are human-owned. Ask the user to edit forge/gates.json themselves.")
        if p == fd / "pii-allowlist.json":
            block("the PII allowlist is human-owned. Ask the user to edit forge/pii-allowlist.json themselves, "
                  "or mark a single synthetic value with 'pii-allow: <reason>' on its line (it stays visible in the gate).")
        if p == fd / "state.json":
            block("forge/state.json (phase, approvals) is owned by state.py; use state.py set/phase/approve.")
        sys.exit(0)

    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command", "")
        destructive = r"(\brm\b|\bmv\b|\bsed\s+-i|\bRemove-Item\b|\bSet-Content\b|\bOut-File\b|" \
                      r"\bAdd-Content\b|\bMove-Item\b|\bdel\b|\bgit\s+(checkout|reset|clean|restore|stash|apply|am)\b)"
        legacy_ref = r"(^|[\s\"'=/\\])legacy[\\/]"
        if re.search(r">{1,2}\s*[\"']?\S*forge[\\/]state\.json", cmd):
            block("redirecting into forge/state.json is not allowed; use state.py")
        m = re.search(r"\bstate\.py[\"']?\s+approve\s+(\w+)", cmd)
        if m:
            ask(f"HUMAN APPROVAL of '{m.group(1)}'. Allow only if YOU approved it in chat. "
                f"Command: {cmd.strip()[:200]}")
        if re.search(r"\b(state|tracker)\.py[\"']?\s[^\n;&|]*--force\b", cmd):
            ask(f"a --force override skips a migration-forge safety check. Allow only if you asked for it. "
                f"Command: {cmd.strip()[:200]}")
        for seg in re.split(r"&&|\|\||;|\n", cmd):
            if re.search(destructive, seg) and re.search(legacy_ref, seg):
                block(f"command would modify legacy/: `{seg.strip()[:160]}`")
            if re.search(r"(>{1,2}|\btee\s+(-a\s+)?)\s*[\"']?[^\s\"'|]*legacy[\\/]", seg):
                block(f"command would write into legacy/: `{seg.strip()[:160]}`")
            if re.search(r">{1,2}\s*[\"']?\S*forge[\\/](gates[\\/]|gates\.json|pii-allowlist\.json|tracker[\\/]tracker\.json|cost[\\/]ledger)", seg):
                block("redirecting into script-owned forge evidence is not allowed")
    sys.exit(0)


if __name__ == "__main__":
    main()
