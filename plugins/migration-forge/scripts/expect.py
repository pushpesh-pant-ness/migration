"""Declarative response checks for `http_expect` eval cases (stdlib).

expect: {"status": 200 | [400, 404],
         "json": {"0.id": {"exists": true}, "*.ssn": {"absent": true}, "total": 90, "name": {"type": "str"}},
         "body_contains": "text", "max_ms": 500}
json operators: equals (a plain value), exists, absent, type (list|dict|str|int|bool|number), min_len, contains, gt, regex.
Paths are dotted; list items by index ("0.id"). A "*" segment checks EVERY element and fails on an empty list -
"0.ssn" only looks at the first record. save: {"new_id": "id"} stores a value for later cases as {{new_id}}.
"""
import re

MISSING = object()
TYPES = {"list": list, "dict": dict, "str": str, "int": int, "bool": bool, "number": (int, float)}
OPS = {"exists", "absent", "type", "min_len", "contains", "gt", "regex"}


def subst(x, v):
    if isinstance(x, str):
        return re.sub(r"\{\{(\w+)\}\}", lambda m: str(v.get(m.group(1), m.group(0))), x)
    if isinstance(x, dict):
        return {k: subst(i, v) for k, i in x.items()}
    if isinstance(x, list):
        return [subst(i, v) for i in x]
    return x


def get_path(o, path):
    for p in str(path).split("."):
        if isinstance(o, list):
            try:
                o = o[int(p)]
            except (ValueError, IndexError):
                return MISSING
        elif isinstance(o, dict) and p in o:
            o = o[p]
        else:
            return MISSING
    return o


def get_all(o, parts):
    """Values at a dotted path where '*' fans out over every list item (or dict value): `*.ssn`, `items.*.price`."""
    if not parts:
        return [o]
    if parts[0] == "*":
        items = o if isinstance(o, list) else list(o.values()) if isinstance(o, dict) else []
        return [v for x in items for v in get_all(x, parts[1:])]
    return get_all(get_path(o, parts[0]), parts[1:])


def match(val, exp):
    if isinstance(exp, dict) and set(exp) <= OPS:
        if exp.get("absent"):
            return val is MISSING
        if val is MISSING:
            return not exp.get("exists", True)
        ok = True
        if "type" in exp:
            ok &= isinstance(val, TYPES.get(exp["type"], object)) and not (exp["type"] == "int" and isinstance(val, bool))
        if "min_len" in exp:
            ok &= hasattr(val, "__len__") and len(val) >= exp["min_len"]
        if "contains" in exp:
            ok &= exp["contains"] in str(val)
        if "gt" in exp:
            ok &= isinstance(val, (int, float)) and val > exp["gt"]
        if "regex" in exp:
            ok &= re.search(exp["regex"], str(val)) is not None
        return ok
    return val == exp


def show(v):
    return "<missing>" if v is MISSING else repr(str(v)[:60])


def check(expect, status, body, text, ms):
    """Return the list of failed expectations (empty = pass). body is parsed JSON or MISSING."""
    errs = []
    want = expect.get("status", 200)
    want = want if isinstance(want, list) else [want]
    if status not in want:
        errs.append(f"status {status}, expected {want}")
    for path, exp in (expect.get("json") or {}).items():
        parts = str(path).split(".")
        if "*" in parts:  # every element must match, and there must be at least one
            vals = [] if body is MISSING else get_all(body, parts)
            bad = next((i for i, v in enumerate(vals) if not match(v, exp)), None)
            if not vals:
                errs.append(f"json[{path}] matched no elements, expected {exp}")
            elif bad is not None:
                errs.append(f"json[{path}] element {bad} = {show(vals[bad])}, expected {exp}")
            continue
        v = MISSING if body is MISSING else get_path(body, path)
        if not match(v, exp):
            errs.append(f"json[{path}] = {show(v)}, expected {exp}")
    if "body_contains" in expect and expect["body_contains"] not in text:
        errs.append(f"body does not contain {expect['body_contains']!r}")
    if "max_ms" in expect and ms > expect["max_ms"]:
        errs.append(f"{ms:.0f}ms > {expect['max_ms']}ms")
    return errs
