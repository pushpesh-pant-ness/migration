"""Shared helpers for migration-forge scripts. Stdlib only."""
import datetime as _dt
import json
import os
import pathlib
import re

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent
FORGE_DIR = "forge"


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
    """Walk up from start (default cwd) to the directory that holds forge/state.json."""
    p = native_path(start or os.getcwd()).resolve()
    for d in [p, *p.parents]:
        if (d / FORGE_DIR / "state.json").exists():
            return d
    return p


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


def load_gates(ws=None):
    """Plugin defaults deep-merged with an optional workspace override at forge/gates.json."""
    base = read_json(PLUGIN_ROOT / "config" / "gates.json", {})
    override = read_json(forge(ws) / "gates.json", {}) or {}
    extra = os.environ.get("FORGE_GATES_OVERRIDE")  # e.g. CI profile without model-produced evidence
    if extra:
        override = _merge_two(override, read_json(extra, {}) or {})

    def merge(a, b):
        out = dict(a)
        for k, v in b.items():
            out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
        return out

    return merge(base, override)


def state(ws=None):
    return read_json(forge(ws) / "state.json", {}) or {}


def save_state(st, ws=None):
    st["updated_at"] = now()
    write_json(forge(ws) / "state.json", st)
