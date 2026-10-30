"""Shared helpers for migration-forge scripts. Stdlib only, no dependency on any AI tool."""
import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

# The toolkit folder (config/, skills/, scripts/). FORGE_ROOT overrides it, e.g. when scripts are copied into a sandbox.
PLUGIN_ROOT = pathlib.Path(os.environ.get("FORGE_ROOT") or pathlib.Path(__file__).resolve().parent.parent)
FORGE_DIR = "forge"
# Build output a legacy build may write; ignored by the legacy fingerprint of a tree that is not a git repo.
BUILD_DIRS = {".git", "node_modules", "target", "bin", "obj", "build", "dist", "out", ".venv", "venv", "__pycache__",
              ".gradle", ".idea", ".vs"}


def now():
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def native_path(s):
    """Accept Git-Bash style /c/Users/... on Windows."""
    m = re.match(r"^/([a-zA-Z])/(.*)", str(s)) if os.name == "nt" else None
    return pathlib.Path(f"{m.group(1)}:/{m.group(2)}" if m else s)


def find_workspace(start):
    """Nearest ancestor of start holding forge/state.json, or None."""
    p = native_path(start).resolve()
    return next((d for d in [p, *p.parents] if (d / FORGE_DIR / "state.json").exists()), None)


def workspace(start=None):
    """Walk up from start (default cwd) to the directory that holds forge/state.json. Exits when there is none, so a
    command run in the wrong folder never creates a stray forge/ there (only `forge state init` makes a workspace)."""
    ws = find_workspace(start or os.getcwd())
    if ws is None:
        sys.exit("no migration workspace here (no forge/state.json in this folder or its parents): "
                 "cd into the workspace, or start a run with `forge state init`")
    return ws


def forge(ws=None):
    return (ws or workspace()) / FORGE_DIR


def read_json(path, default=None):
    path = pathlib.Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _merge_two(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge_two(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_settings(ws=None):
    """Plugin defaults (config/settings.json) deep-merged with an optional workspace override at forge/settings.json."""
    base = read_json(PLUGIN_ROOT / "config" / "settings.json", {})
    return _merge_two(base, read_json(forge(ws) / "settings.json", {}) or {})


def state(ws=None):
    return read_json(forge(ws) / "state.json", {}) or {}


def save_state(st, ws=None):
    st["updated_at"] = now()
    write_json(forge(ws) / "state.json", st)


def git_out(ws, *args):
    """stdout of `git <args>` run in ws, or None when git fails."""
    try:
        p = subprocess.run(["git", *args], cwd=ws, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def git_head(ws):
    out = git_out(ws, "rev-parse", "HEAD")
    return out.strip() if out else None


def not_code(ws, card=None):
    """Workspace folders whose changes are not code: forge/ (the run's own evidence) and the folder a verdict was
    imported from when it lies inside the workspace (a downloaded summary.json)."""
    out = ["forge"]
    loc = (card or {}).get("location") or ""
    if loc and not re.match(r"https?://", loc):
        try:
            rel = native_path(loc).resolve().parent.relative_to(pathlib.Path(ws).resolve())
            if rel.parts:
                out.append(rel.as_posix())
        except (ValueError, OSError):
            pass
    return out


def code_changes(ws, base, uncommitted=False, exclude=("forge",)):
    """Tracked files outside `exclude` that differ between commit `base` and HEAD (with uncommitted: and the working
    tree). Committing a verdict or a phase move is not a code change. None when git can't tell (unknown commit...)."""
    out = git_out(ws, "diff", "--name-only", base, *([] if uncommitted else ["HEAD"]), "--", ".",
                  *[f":(exclude){x}" for x in exclude])
    return None if out is None else [x for x in out.splitlines() if x.strip()]


def verdict_covers_code(ws, card):
    """True when `card` is a commit-verified Jenkins PASS and no code changed since the commit it tested."""
    if not card or card.get("verdict") != "PASS" or not card.get("head") or not card.get("commit_verified"):
        return False
    return code_changes(ws, card["head"], uncommitted=True, exclude=not_code(ws, card)) == []


def link_dir(link, target):
    """Make `link` point at the directory `target`: a symlink, or a junction on Windows when symlinks need admin."""
    link, target = pathlib.Path(link), pathlib.Path(target).resolve()
    if link.exists() or link.is_symlink():
        return link.resolve() == target
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        if os.name != "nt":
            raise
    p = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    return p.returncode == 0


def tree_fingerprint(root):
    """A digest that changes when the legacy source changes. In a git repo: HEAD plus tracked modifications
    (build output and other untracked files don't count). Otherwise: path, size and mtime of every file outside
    BUILD_DIRS. None when root is missing."""
    root = pathlib.Path(root)
    if not root.is_dir():
        return None
    try:
        h = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
        s = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, timeout=120)
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if h.returncode == 0 and s.returncode == 0 and native_path(top.stdout.strip()).resolve() == root.resolve():
            return "git:" + h.stdout.strip() + ":" + hashlib.sha256(s.stdout.encode()).hexdigest()[:16]
    except (OSError, subprocess.TimeoutExpired):
        pass
    d = hashlib.sha256()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in BUILD_DIRS)
        for f in sorted(files):
            p = pathlib.Path(dirpath) / f
            try:
                stt = p.stat()
            except OSError:
                continue
            d.update(f"{p.relative_to(root).as_posix()}|{stt.st_size}|{stt.st_mtime_ns}\n".encode())
    return "files:" + d.hexdigest()[:32]
