#!/usr/bin/env python3
"""Workspace guard (active only inside a migration workspace, i.e. forge/state.json exists).

The rules are plain functions, so any host can enforce them:
  - Claude Code: hooks/hooks.json runs this file as a PreToolUse hook (JSON event on stdin).
  - Any other tool with a pre-tool or pre-command hook, a sandbox wrapper, or a human:
        forge guard path <file>        # before writing a file
        forge guard cmd "<command>"    # before running a shell command
        forge guard legacy             # has the legacy source changed since the run started? (git pre-commit)
    Exit 0 allow, 2 block (reason on stderr), 3 ask a human first (reason on stderr).

Blocks:
  - any write into legacy/ or the original repo path (legacy code is read-only evidence)
  - hand edits of script-owned evidence: tracker.json, history.log, the imported Jenkins verdicts
    (forge/gates/), db/verify.json
  - edits of forge/settings.json (remediation cap, budgets): changed by humans, outside the agent
  - hand edits of forge/state.json (phase + approvals live there)
  - shell commands that change those paths: deleting, moving, copying onto, editing in place or redirecting into them,
    git commands that rewrite files there (including `git -C legacy/...`), builds and package installs run inside
    legacy/, and the same inside `cd legacy/... && ...`, `bash -c "..."`, `... | xargs rm` and `find ... -delete`.
    Paths are resolved, so the original repo's absolute path counts as legacy too.
Asks (a human must confirm):
  - state.py approve ...    (human checkpoints must be confirmed by a human)
  - state.py / tracker.py ... --force, and `forge db reversibility --allow-remote`
  - inline scripts (python -c, node -e, ...) that name legacy/ or forge evidence and look like they write
This is a tripwire against mistakes, not a sandbox: a determined script can still write anywhere. For a hard boundary,
mount the legacy repo read-only (AGENTS.md).
"""
import glob
import json
import os
import pathlib
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from forgelib import FORGE_DIR, find_workspace as find_ws, native_path, read_json, tree_fingerprint  # noqa: E402

OWNED = [("tracker", "tracker.json"), ("tracker", "history.log"), ("db", "verify.json")]
ALLOW, BLOCK, ASK = "allow", "block", "ask"
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell")

# Shell command vocabulary (lower case; PowerShell aliases included).
CD = {"cd", "pushd", "chdir", "set-location", "sl", "push-location"}
DELETERS = {"rm", "rmdir", "unlink", "shred", "del", "erase", "rd", "remove-item", "ri", "mv", "move", "move-item", "mi",
            "ren", "rename", "rename-item", "rni"}
WRITERS = DELETERS | {"ln", "touch", "truncate", "dd", "chmod", "chown", "chgrp", "tee", "mkdir", "patch", "mklink",
                      "new-item", "ni", "set-content", "sc", "add-content", "ac", "clear-content", "clc", "out-file",
                      "set-itemproperty"}
COPIERS = {"cp", "rsync", "install", "copy", "xcopy", "robocopy", "copy-item", "cpi", "scp"}  # only the destination changes
IN_PLACE = {"sed", "perl", "awk", "gawk"}  # with -i
BUILDERS = {"npm", "npx", "yarn", "pnpm", "bun", "composer", "bundle", "mvn", "gradle", "gradlew", "dotnet", "go",
            "cargo", "make", "ant"}
BUILDER_DIR_OPTS = {"--prefix", "-c", "--cwd", "--dir", "--directory", "--project-dir"}
GIT_WRITE = {"checkout", "reset", "clean", "restore", "stash", "apply", "am", "rm", "mv", "switch", "pull", "merge",
             "rebase", "cherry-pick", "revert", "commit", "add", "worktree", "submodule", "update-index", "init"}
GIT_EVIDENCE_WRITE = {"checkout", "restore", "reset", "rm", "mv", "clean", "stash", "apply", "am"}
SHELLS = {"bash", "sh", "zsh", "dash", "cmd", "powershell", "pwsh"}
INTERPRETERS = {"python", "python3", "py", "node", "perl", "ruby", "php", "deno"}
INLINE_FLAGS = {"-c", "-e", "-r", "--eval", "-command", "/c", "/k", "eval"}
WRITE_ISH = re.compile(r"open\([^)]*['\"][wax+]|\.write|writefile|appendfile|unlink|remove|rmtree|rmsync|rename|replace\("
                       r"|truncate|mkdir|copy|move|json\.dump\(|set-content|out-file", re.I)
EVIDENCE_NAME = re.compile(r"(^|[\\/\s'\"])(legacy[\\/]|forge[\\/](state\.json|settings\.json|gates|tracker[\\/]"
                           r"(tracker\.json|history\.log)|db[\\/]verify\.json))", re.I)


def inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def legacy_roots(ws, st):
    roots = [(ws / "legacy").resolve()]
    if st.get("repo"):
        roots.append(pathlib.Path(st["repo"]).resolve())
    return roots


def check_path(ws, st, raw):
    """Decision for writing the file `raw` (absolute, or relative to the workspace)."""
    p = native_path(raw)
    p = (p if p.is_absolute() else ws / p).resolve()
    fd = (ws / FORGE_DIR).resolve()
    if any(inside(p, r) for r in legacy_roots(ws, st)):
        return BLOCK, f"{p} is legacy source (read-only). Write new code under modernized/ instead."
    for sub, name in OWNED:
        if p == fd / sub / name:
            return BLOCK, f"{p.name} is owned by migration-forge scripts; use forge tracker / forge db."
    if inside(p, fd / "gates"):
        return BLOCK, "gate verdicts come only from Jenkins via `forge gate import`; fix the code, let Jenkins build it, then import."
    if p == fd / "settings.json":
        return BLOCK, "forge/settings.json (remediation cap, budgets) is human-owned. Ask the user to edit it themselves."
    if p == fd / "state.json":
        return BLOCK, "forge/state.json (phase, approvals) is owned by state.py; use forge state set/phase/approve."
    if p == fd / "PAUSE":
        return _blocked("pause", str(p))
    return ALLOW, ""


class _Paths:
    """Classifies the paths a shell command names: legacy source, script-owned evidence, or neither."""

    def __init__(self, ws, st):
        self.ws = ws
        self.legacy = legacy_roots(ws, st)
        fd = (ws / FORGE_DIR).resolve()
        self.gates, self.pause = fd / "gates", fd / "PAUSE"
        self.evidence = [fd / "state.json", fd / "settings.json", fd / "tracker" / "tracker.json",
                         fd / "tracker" / "history.log", fd / "db" / "verify.json", self.gates]

    @staticmethod
    def _text(tok):
        tok = tok.strip("\"'")
        if re.match(r"^-*[\w-]+=", tok):  # --output=x, of=x
            tok = tok.split("=", 1)[1]
        if not tok or tok.startswith("-") or tok.lower() in ("nul", "$null") or tok.startswith("/dev/"):
            return None
        return tok

    def resolve(self, tok, cwd):
        tok = self._text(tok or "")
        if tok is None or re.search(r"[$%*?]", tok):
            return None
        try:
            p = native_path(os.path.expanduser(tok))
            return (p if p.is_absolute() else cwd / p).resolve()
        except (OSError, ValueError, RuntimeError):
            return None

    def _classify(self, p, contains):
        if any(inside(p, r) or (contains and inside(r, p)) for r in self.legacy):
            return "legacy"
        if inside(p, self.gates) or p in self.evidence or (contains and any(inside(e, p) for e in self.evidence)):
            return "evidence"
        return "pause" if p == self.pause else None

    def kind(self, tok, cwd, contains=False):
        """'legacy', 'evidence', 'pause' or None for the path `tok`. With contains, a folder that holds legacy or
        evidence counts too (deleting or moving it would take them along)."""
        text = self._text(tok)
        if text is None:
            return None
        if re.search(r"[*?]", text) and "$" not in text and "%" not in text:  # a glob: check what it expands to
            pattern = text if native_path(text).is_absolute() else str(cwd / text)
            hits = [self._classify(pathlib.Path(x).resolve(), contains) for x in glob.glob(pattern)[:5000]]
            found = next((h for h in hits if h), None)
            if found or hits:
                return found
        p = self.resolve(text, cwd)
        if p is None:  # variables or a glob with no match: judge by the text
            if re.search(r"(^|[\\/\s\"'=])legacy([\\/]|$)", text):
                return "legacy"
            return "evidence" if EVIDENCE_NAME.search(" " + text) else None
        return self._classify(p, contains)


def _lex(seg):
    lx = shlex.shlex(seg, posix=True)
    lx.whitespace_split, lx.escape, lx.commenters = True, "", ""
    try:
        return list(lx)
    except ValueError:  # unbalanced quotes
        return seg.split()


def _segments(cmd):
    """(separator before, text) for each simple command; separators are ; && || | and newlines."""
    out, last = [], 0
    for m in re.finditer(r"\|\||&&|[;\n|]", cmd):
        out.append(cmd[last:m.start()])
        out.append(m.group())
        last = m.end()
    out.append(cmd[last:])
    return [(out[i - 1] if i else "", out[i]) for i in range(0, len(out), 2)]


REDIRECT = re.compile(r"(?<![<>])(?:\d|&)?>{1,2}\|?\s*(\"[^\"]*\"|'[^']*'|[^\s|;&<>]+)")


def _blocked(kind, what):
    if kind == "pause":
        return ASK, (f"forge/PAUSE switches off the remediation obligation (the Stop hook and `forge next`). "
                     f"Allow only if you asked to pause the run: `{what[:160]}`")
    if kind == "legacy":
        return BLOCK, f"command would modify legacy source (read-only; build it in a scratch/ copy): `{what[:160]}`"
    return BLOCK, (f"command would change script-owned evidence in forge/ (only `forge` writes it; forge/settings.json "
                   f"is the human's): `{what[:160]}`")


def _check_shell(paths, cmd, cwd, depth=0):
    """(decision, message) for the shell text `cmd` run in `cwd`. Recurses into `bash -c "..."` and the like."""
    ask = None
    prev_protected = None
    for sep, seg in _segments(cmd):
        text = seg.strip()
        if not text:
            continue
        for m in REDIRECT.finditer(text):
            target = m.group(1)
            if not target.startswith("&") and (k := paths.kind(target, cwd)):
                return _blocked(k, text)
        toks = _lex(REDIRECT.sub(" ", text))
        while toks and (toks[0].lower() in ("sudo", "env", "command", "exec", "time", "nohup", "&", ".")
                        or re.match(r"^\w+=", toks[0])):
            toks = toks[1:]
        if not toks:
            continue
        name = re.sub(r"\.(exe|cmd|bat|ps1)$", "", toks[0].replace("\\", "/").rsplit("/", 1)[-1].lower())
        args = toks[1:]
        if name == "xargs":
            i = 0
            while i < len(args) and args[i].startswith("-"):
                i += 2 if args[i] in ("-n", "-I", "-L", "-P", "-d", "-E", "-s", "-a") else 1
            name, args = (args[i].lower(), args[i + 1:]) if i < len(args) else ("", [])
        piped_from = prev_protected if sep == "|" else None
        refs = [k for t in args if (k := paths.kind(t, cwd))]
        prev_protected = refs[0] if refs else None
        if name in CD:
            target = next((t for t in args if not t.startswith("-")), None)
            p = paths.resolve(target, cwd) if target and target != "-" else paths.ws
            cwd = p if p is not None else cwd
            continue
        here = paths.kind(str(cwd), cwd)
        if name in SHELLS:
            inner = next((i for i, t in enumerate(args) if t.lower() in INLINE_FLAGS), None)
            if inner is not None and depth < 3:
                d, msg = _check_shell(paths, " ".join(args[inner + 1:]), cwd, depth + 1)
                if d == BLOCK:
                    return d, msg
                ask = ask or (msg if d == ASK else None)
            continue
        if name in INTERPRETERS and any(t.lower() in INLINE_FLAGS for t in args):
            code = " ".join(args)
            if (EVIDENCE_NAME.search(" " + code) or (here and re.search(r"['\"]", code))) and WRITE_ISH.search(code):
                ask = ask or f"an inline script names legacy/ or forge evidence and may write to it: `{text[:160]}`"
            continue
        if name == "git":
            target, i = cwd, 0
            while i < len(args) and args[i].startswith("-"):
                if args[i] == "-C" and i + 1 < len(args):
                    target = paths.resolve(args[i + 1], target) or target
                    i += 1
                elif args[i] == "-c":
                    i += 1
                i += 1
            sub = args[i].lower() if i < len(args) else ""
            sub_args = args[i + 1:]
            if sub in GIT_WRITE and paths.kind(str(target), target) == "legacy":
                return _blocked("legacy", text)
            if sub in GIT_WRITE and any(paths.kind(t, target) == "legacy" for t in sub_args):
                return _blocked("legacy", text)
            if sub in GIT_EVIDENCE_WRITE and any(paths.kind(t, target) == "evidence" for t in sub_args):
                return _blocked("evidence", text)
            continue
        if name == "find":
            if any(t in ("-delete", "-exec", "-execdir", "-ok") for t in args) and (refs or here):
                return _blocked(refs[0] if refs else here, text)
            continue
        if name in WRITERS or (name in IN_PLACE and any(re.match(r"^-[a-z]*i", t) for t in args)):
            contains = name in DELETERS
            hit = next((k for t in args if (k := paths.kind(t, cwd, contains=contains))), None)
            no_paths = not [t for t in args if not t.startswith("-")]
            if hit or (piped_from and no_paths):  # `... legacy ... | xargs rm`, `Get-ChildItem legacy | Remove-Item`
                return _blocked(hit or piped_from, text)
            continue
        if name in COPIERS:
            dest = None
            for j, t in enumerate(args):
                if t.lower() in ("-destination", "--target-directory", "-t") and j + 1 < len(args):
                    dest = args[j + 1]
            # positional arguments; /E, /MIR, /S... are xcopy/robocopy switches
            pos = [t for t in args if not t.startswith("-") and not re.fullmatch(r"/[A-Za-z]+(:\S*)?", t)]
            if not dest and len(pos) >= 2:
                dest = pos[1] if name == "robocopy" else pos[-1]
            if dest and (k := paths.kind(dest, cwd)):
                return _blocked(k, text)
            continue
        if name in BUILDERS:
            dirs = [args[j + 1] for j, t in enumerate(args[:-1]) if t.lower() in BUILDER_DIR_OPTS]
            dirs += [t.split("=", 1)[1] for t in args if t.lower().split("=", 1)[0] in BUILDER_DIR_OPTS and "=" in t]
            hit = here or next((k for d in dirs if (k := paths.kind(d, cwd)) == "legacy"), None)
            if hit == "legacy":
                return _blocked("legacy", text)
    return (ASK, ask) if ask else (ALLOW, "")


def check_command(ws, st, cmd, cwd=None):
    """Decision for running the shell command `cmd`, started in `cwd` (default: the workspace)."""
    start = native_path(cwd).resolve() if cwd else ws
    decision, msg = _check_shell(_Paths(ws, st), cmd, start)
    if decision == BLOCK:
        return decision, msg
    m = re.search(r"\b(?:state\.py[\"']?|forge(?:\.py|\.cmd)?[\"']?\s+state)\s+approve\s+(\w+)", cmd)
    if m:
        return ASK, (f"HUMAN APPROVAL of '{m.group(1)}'. Allow only if YOU approved it in chat. "
                     f"Command: {cmd.strip()[:200]}")
    if re.search(r"\b(?:(?:state|tracker)\.py[\"']?|forge(?:\.py|\.cmd)?[\"']?\s+(?:state|tracker))\s[^\n;&|]*--force\b", cmd):
        return ASK, (f"a --force override skips a migration-forge safety check. Allow only if you asked for it. "
                     f"Command: {cmd.strip()[:200]}")
    if re.search(r"\b(?:db_verify\.py[\"']?|forge(?:\.py|\.cmd)?[\"']?\s+db)\s+reversibility\b[^\n;&|]*--allow-remote", cmd):
        return ASK, ("`forge db reversibility --allow-remote` runs up/down migrations against a non-local database. "
                     f"Allow only if you confirm that database is disposable. Command: {cmd.strip()[:200]}")
    if decision == ASK:
        return ASK, msg
    return ALLOW, ""


def check_legacy(ws, st):
    """Has the legacy repo changed since `state init` recorded its fingerprint?"""
    want = st.get("legacy_fingerprint")
    if not want or not st.get("repo"):
        return ALLOW, ""
    got = tree_fingerprint(st["repo"])
    if got != want:
        return BLOCK, (f"the legacy source at {st['repo']} changed since the run started ({want} -> {got}). "
                       "It is read-only: revert the change there (e.g. git -C <repo> restore .).")
    return ALLOW, ""


def hook_main():
    """Claude Code PreToolUse adapter: JSON event on stdin; exit 2 blocks, a permissionDecision 'ask' prompts."""
    try:
        ev = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)
    cwd = ev.get("cwd") or os.getcwd()
    tool, ti = ev.get("tool_name", ""), ev.get("tool_input") or {}
    raw = (ti.get("file_path") or ti.get("notebook_path")) if tool in WRITE_TOOLS else None
    # The session may sit outside the workspace (a parent folder, say): a file write is judged by the file's own run.
    ws = find_ws(cwd) or (find_ws(native_path(raw).parent) if raw and native_path(raw).is_absolute() else None)
    if not ws:
        sys.exit(0)
    st = read_json(ws / FORGE_DIR / "state.json", {}) or {}
    if tool in WRITE_TOOLS:
        decision, msg = check_path(ws, st, raw) if raw else (ALLOW, "")
    elif tool in SHELL_TOOLS:
        decision, msg = check_command(ws, st, ti.get("command", ""), cwd)
    else:
        decision, msg = ALLOW, ""
    if decision == BLOCK:
        print(f"migration-forge guard: {msg}", file=sys.stderr)
        sys.exit(2)
    # EVAL_FORGE_AUTO_APPROVE=1 (set only by `claude plugin eval` case env, never by the model:
    # Bash commands cannot change the hook's environment) skips the prompt for headless eval runs.
    if decision == ASK and os.environ.get("EVAL_FORGE_AUTO_APPROVE") != "1":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                 "permissionDecisionReason": f"migration-forge: {msg}"}}))
    sys.exit(0)


def cli(argv):
    """forge guard path <file> | cmd <command> | legacy  ->  exit 0 allow, 2 block, 3 ask."""
    if not argv or argv[0] not in ("path", "cmd", "legacy") or (argv[0] != "legacy" and len(argv) < 2):
        sys.exit("usage: forge guard path <file> | cmd <command> | legacy")
    ws = find_ws(os.getcwd())
    if not ws:
        sys.exit(0)
    st = read_json(ws / FORGE_DIR / "state.json", {}) or {}
    what = " ".join(argv[1:])
    decision, msg = {"path": lambda: check_path(ws, st, what), "cmd": lambda: check_command(ws, st, what, os.getcwd()),
                     "legacy": lambda: check_legacy(ws, st)}[argv[0]]()
    if decision != ALLOW:
        print(f"migration-forge guard ({decision}): {msg}", file=sys.stderr)
    sys.exit({ALLOW: 0, BLOCK: 2, ASK: 3}[decision])


if __name__ == "__main__":
    hook_main()
