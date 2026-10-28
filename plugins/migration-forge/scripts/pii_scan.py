#!/usr/bin/env python3
"""PII/PHI and hardcoded-credential scanner (stdlib). Feeds the `pii` and `security` gate checks.

  pii_scan.py [<dir>]            # print a JSON summary (default: state.modernized_root)

Detects SSN, Aadhaar (Verhoeff), PAN, payment cards (Luhn + issuer prefix, published test numbers ignored), e-mail
(allowlisted fake domains), phone, DOB; PII values passed to log/print calls; hardcoded credentials. Output is masked.
Allowlist: config/pii-allowlist.json, extended by forge/pii-allowlist.json. A line containing `pii-allow: <reason>`
suppresses its PII findings, but each suppression is still reported (rule pii-allowed:*) and counted.
"""
import json
import os
import pathlib
import re
import sys

from forgelib import PLUGIN_ROOT, forge, read_json, state, workspace

# Published payment-network test numbers (Stripe/Adyen/Braintree docs): sample data, not cardholder data.
TEST_CARDS = {"4111111111111111", "4242424242424242", "4012888888881881", "4000056655665556", "5555555555554444",
              "5105105105105100", "2223003122003222", "378282246310005", "371449635398431", "6011111111111117",
              "6011000990139424", "3566002020360505", "30569309025904", "38520000023237"}
ALLOW = re.compile(r"pii-allow:\s*(\S.*)")


def config(ws=None):
    cfg = read_json(PLUGIN_ROOT / "config" / "pii-allowlist.json", {})
    extra = read_json(forge(ws) / "pii-allowlist.json", {}) if ws else {}
    for k, v in (extra or {}).items():
        if isinstance(v, list):
            cfg[k] = list(cfg.get(k, [])) + v
    return cfg


def luhn(s):
    d = [int(c) for c in re.sub(r"\D", "", s)]
    if not 13 <= len(d) <= 19:
        return False
    t = 0
    for i, x in enumerate(reversed(d)):
        if i % 2:
            x = x * 2 - 9 if x * 2 > 9 else x * 2
        t += x
    return t % 10 == 0


_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
       [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
       [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
       [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
       [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
       [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff(s):
    """Aadhaar numbers carry a Verhoeff check digit; this drops ~90% of look-alike 12-digit runs."""
    c = 0
    for i, x in enumerate(reversed(re.sub(r"\D", "", s))):
        c = _VD[c][_VP[i % 8][int(x)]]
    return c == 0


_CRED_WORD = r"(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|token)"
CRED_LIT = re.compile(rf"""(?i)(\w*{_CRED_WORD}\w*)["']?\s*[:=]\s*["']([^"'\s]{{4,}})["']""")
CRED_CFG = re.compile(r"(?im)^\s*([\w.\-]*(?:password|secret|api[_-]?key|token)[\w.\-]*)\s*[:=]\s*([^\s#\"'$\{<][^\s#]*)\s*$")
# Keys that NAME a credential-related thing rather than hold one: pwdSelector, passwordLabel, tokenType, jwt.token.expiry
NOT_A_SECRET = re.compile(r"(?i)(selector|field|label|input|placeholder|hint|prompt|message|msg|text|title|header|url|uri|"
                          r"path|route|endpoint|regex|pattern|policy|length|len|min|max|ttl|timeout|expiry|expires|count|"
                          r"enabled|required|type|name|id|attempts)$")
CFG_EXT = (".properties", ".yml", ".yaml", ".env", ".conf", ".ini", ".toml", ".cfg")
PLACEHOLDER = re.compile(r"\$\{|\{\{|%\(|<[^>]+>|getenv|environ|process\.env|^x{3,}$|^\*+$|^changeme$", re.I)
LOG_CALL = re.compile(r"(?i)(?:log\w*\.\w+|logger\.\w+|\bprint|console\.\w+|System\.out\.print\w*|println)\s*\((.*)")
STR_LIT = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")
INTERP = re.compile(r"\$\{([^}]*)\}|\{([^{}]+)\}")                                        # f"{p.ssn}", `${p.phone}`
LABEL = re.compile(r"([A-Za-z_]\w*)\s*[=:]\s*(?:%[-\d.]*[sdrfx]|\{[^}]*\}|\$\{)")      # "ssn=%s", "email: {}"
PII_WORDS = {"ssn", "aadhaar", "password", "passwd", "dob", "phone", "email", "card", "diagnosis"}


def log_pii(line):
    """PII *values* passed to a log/print call. Plain message text ("Sending reminder email") is not a leak, so string
    literals count only when they are a key ("ssn" in d.get("ssn")), a labelled placeholder ("ssn=%s"), or an
    interpolation (f"{p.email}"). Identifiers are split on camelCase/snake_case, so getEmail matches but discard doesn't."""
    m = LOG_CALL.search(line)
    if not m:
        return False
    code = []
    for lit in STR_LIT.findall(m.group(1)):
        s = lit[1:-1]
        if re.fullmatch(r"[A-Za-z_]\w*", s):
            code.append(s)
        code += [a or b for a, b in INTERP.findall(s)] + LABEL.findall(s)
    code.append(STR_LIT.sub(" ", m.group(1)))
    words = {w.lower() for ident in re.findall(r"[A-Za-z_]\w*", " ".join(code))
             for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", ident)}
    return bool(words & PII_WORDS)


def detectors(cfg):
    ok_domains = tuple(d.lower() for d in cfg.get("email_domains", []))
    test_cards = TEST_CARDS | {re.sub(r"\D", "", str(c)) for c in cfg.get("test_card_numbers", [])}

    def card(s):
        """Luhn alone passes 1 in 10 random digit runs, so also require a real issuer prefix."""
        d = re.sub(r"\D", "", s)
        if d in test_cards or not luhn(d):
            return False
        return d[0] in "3456" or (d[0] == "2" and 2221 <= int(d[:4]) <= 2720) or d[:2] in ("81", "82")

    def real_email(s):
        dom = s.rsplit("@", 1)[-1].lower()
        return not any(dom == ok or dom.endswith("." + ok) for ok in ok_domains)  # exact domain or subdomain only

    return {  # name: (regex, validator)
        "ssn": (re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"), None),
        "aadhaar": (re.compile(r"(?<!\d)(?<!\d[ -])[2-9]\d{3}[ -]\d{4}[ -]\d{4}(?![ -]?\d)"), verhoeff),
        "pan": (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), None),
        "credit_card": (re.compile(r"\b(?:\d[ -]?){13,19}\b"), card),
        "email": (re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b"), real_email),
        "phone": (re.compile(r"(?<![\d.])(?:\+?91[- ]?)?[6-9]\d{9}(?![\d.])|(?<![\d.])\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?![\d.])"), None),
        "dob": (re.compile(r"(?i)\b(?:dob|date_of_birth|birth_?date)\b[\"'\s:=,]{1,6}\d{4}-\d{2}-\d{2}"), None),
    }


def mask(s):
    return s[:2] + "*" * max(len(s) - 2, 2)


def files(root, cfg):
    skip_d, skip_e, skip_f = set(cfg["skip_dirs"]), tuple(cfg["skip_extensions"]), set(cfg["skip_files"])
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in skip_d]
        for f in fn:
            p = pathlib.Path(dp) / f
            if f in skip_f or f.lower().endswith(skip_e):
                continue
            try:
                if p.stat().st_size > 1_000_000:
                    continue
                data = p.read_bytes()
            except OSError:
                continue
            if b"\0" in data[:1024]:
                continue
            yield p, data.decode("utf-8", "ignore")


def scan(root, cfg):
    """Return {"pii": [...], "logs": [...], "creds": [...], "allowed": [...], "files": n}; findings are masked."""
    pii = detectors(cfg)
    out = {"pii": [], "logs": [], "creds": [], "allowed": [], "files": 0}
    root = pathlib.Path(root)
    for p, text in files(root, cfg):
        out["files"] += 1
        rel = p.relative_to(root).as_posix()
        for n, line in enumerate(text.splitlines(), 1):
            if len(line) > 2000:
                continue
            hits = [{"tool": "pii", "severity": "high", "file": rel, "line": n, "rule": name, "msg": f"{name} found: {mask(m.group(0))}"}
                    for name, (rx, val) in pii.items() for m in rx.finditer(line) if val is None or val(m.group(0))]
            if log_pii(line):
                hits.append({"tool": "pii", "severity": "medium", "file": rel, "line": n, "rule": "pii-in-logs",
                             "msg": "PII/PHI field written to log/stdout"})
            ok = ALLOW.search(line)
            if ok and hits:  # suppressed, but never silently: each one is listed with its reason
                out["allowed"] += [dict(h, severity="info", rule=f"pii-allowed:{h['rule']}",
                                        msg=f"{h['msg']} (allowed: {ok.group(1)[:80]})") for h in hits]
            else:
                out["pii"] += [h for h in hits if h["rule"] != "pii-in-logs"]
                out["logs"] += [h for h in hits if h["rule"] == "pii-in-logs"]
            for rx in [CRED_LIT] + ([CRED_CFG] if rel.lower().endswith(CFG_EXT) else []):
                m = rx.search(line)
                if m and not PLACEHOLDER.search(m.group(2)) and not NOT_A_SECRET.search(m.group(1)):
                    out["creds"].append({"tool": "creds", "severity": "critical", "file": rel, "line": n,
                                         "rule": "hardcoded-credential", "msg": f"{m.group(1)} = {mask(m.group(2))}"})
                    break
    return out


if __name__ == "__main__":
    ws = workspace()
    target = sys.argv[1] if len(sys.argv) > 1 else (state().get("modernized_root") or ".")
    r = scan(ws / target if not os.path.isabs(target) else target, config(ws))
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in r.items()}, indent=2))
    for f in (r["creds"] + r["pii"] + r["logs"] + r["allowed"])[:50]:
        print(f"{f['file']}:{f['line']} [{f['severity']}] {f['rule']} - {f['msg']}")
