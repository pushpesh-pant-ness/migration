#!/usr/bin/env python3
"""Apply gate thresholds (config/gates.json + forge/gates.json override) to a scorecard.

  score.py [forge/gates/latest.json]      # re-score in place and print the verdict

Rules: a required check that was skipped/errored FAILS. A check with status 'n/a'
(e.g. no database in this project) is excluded. Verdict PASS iff every required check
passes and overall_score >= min_overall_score.
"""
import json
import sys

from forgelib import forge, load_gates, read_json, write_json


def _pct(v):
    return max(0.0, min(100.0, float(v)))


def judge(name, c, t):
    """Return (passed, score_0_100, reasons) for one measured check."""
    m, r = c.get("metrics", {}), []
    if name == "tests":
        failed, total = m.get("failed"), m.get("total")
        if failed is None:
            r.append("test result unknown")
        elif failed > t.get("max_failed", 0):
            r.append(f"{failed} failing test(s) > {t.get('max_failed', 0)}")
        if total is not None and total < t.get("min_total", 1):
            r.append(f"only {total} test(s) ran (< {t.get('min_total', 1)})")
        ok = not r
        score = 100 if ok else (0 if not total else _pct(100 * (total - (failed or total)) / total))
        return ok, score, r
    if name == "coverage":
        diff = m.get("diff_line_pct")
        if diff is not None:  # changed-line coverage is the meaningful number for migrated code
            pct, need, label = diff, t.get("min_diff_line_pct", 80), "changed-line coverage"
        else:
            pct, need, label = m.get("line_pct"), t.get("min_line_pct", 80), "overall line coverage"
        if pct is None:
            return False, 0, ["coverage not measured"]
        ok = pct >= need
        return ok, _pct(100 * pct / need) if need else 100, [] if ok else [f"{label} {pct:.1f}% < {need}%"]
    if name == "review":
        for sev in ("blocking", "major"):
            n, mx = m.get(sev, 0), t.get(f"max_{sev}", 0)
            if n > mx:
                r.append(f"{n} {sev} review finding(s) > {mx}" + (f": {m['top'][0]}" if m.get("top") else ""))
        return not r, max(0, 100 - 40 * m.get("blocking", 0) - 5 * m.get("major", 0)), r
    if name in ("lint", "typecheck"):
        n, mx = m.get("errors"), t.get("max_errors", 0)
        if n is None:
            return False, 0, [f"{name} not measured"]
        ok = n <= mx
        return ok, 100 if ok else max(0, 100 - 10 * n), [] if ok else [f"{n} {name} error(s) > {mx}"]
    if name == "security":
        for sev in ("critical", "high", "secrets"):
            n, mx = m.get(sev, 0), t.get(f"max_{sev}", 0)
            if n > mx:
                r.append(f"{n} {sev} finding(s) > {mx}")
        nl, ml = m.get("license_violations", 0), t.get("max_license_violations", 0)
        if nl > ml:
            r.append(f"{nl} forbidden/restricted licence(s) > {ml}: {', '.join(m.get('license_findings', [])[:3])}")
        if m.get("claude_security") == "missing" and t.get("require_claude_security", True):
            r.append("claude-security verified scan summary missing (forge/evidence/claude-security.json)")
        if not m.get("scanners_ran"):
            r.append("no security scanner ran")
        pen = 40 * m.get("critical", 0) + 20 * m.get("high", 0) + 40 * m.get("secrets", 0) + 2 * m.get("medium", 0)
        return not r, max(0, 100 - pen) if not r or pen else 0, r
    if name == "behavior":
        np_, pp = m.get("not_proven"), m.get("partly_proven")
        if np_ is not None:
            if np_ > t.get("max_not_proven", 0):
                r.append(f"{np_} module(s) NOT PROVEN")
            if pp > t.get("max_partly_proven", 0):
                r.append(f"{pp} module(s) PARTLY PROVEN")
        acc = m.get("acceptance_pass_pct")
        if acc is not None and acc < t.get("min_acceptance_pass_pct", 100):
            r.append(f"acceptance pass rate {acc:.1f}% < {t.get('min_acceptance_pass_pct', 100)}%")
        if np_ is None and acc is None:
            r.append("no behavioral evidence (VERIFICATION.md or forge/evals/results.json)")
        total = (m.get("proven") or 0) + (pp or 0) + (np_ or 0)
        parts = ([100 * ((m.get("proven") or 0) + 0.5 * (pp or 0)) / total] if total else []) + ([acc] if acc is not None else [])
        return not r, _pct(sum(parts) / len(parts)) if parts else 0, r
    if name == "database":
        rm = m.get("row_match_pct")
        if rm is None:
            r.append("no data verification (run db_verify.py)")
        elif rm < t.get("min_row_match_pct", 100):
            r.append(f"row/checksum match {rm:.2f}% < {t.get('min_row_match_pct', 100)}%")
        if t.get("require_reversible", True) and m.get("reversible") is not True:
            r.append("migrations not proven reversible (up/down/up)")
        if (m.get("lint_errors") or 0) > t.get("max_lint_errors", 0):
            r.append(f"{m['lint_errors']} migration lint error(s)")
        return not r, _pct(rm or 0) if not r else _pct((rm or 0) * 0.5), r
    if name == "cost":
        tok, mt = m.get("tokens_total"), t.get("max_tokens", 0)
        if mt and tok is not None and tok > mt:
            r.append(f"token spend {tok:,} > budget {mt:,}")
        mu, cap = m.get("monthly_usd"), t.get("max_monthly_usd", 0)
        if cap and mu is not None and mu > cap:
            r.append(f"monthly infra ${mu:,.2f} > cap ${cap:,.2f}")
        inc, capi = m.get("monthly_increase_pct"), t.get("max_monthly_increase_pct")
        if capi is not None and inc is not None and inc > capi:
            r.append(f"monthly infra +{inc:.1f}% vs legacy > +{capi}%")
        return not r, 100 if not r else 40, r
    if name == "performance":
        reg = m.get("p95_regression_pct")
        if reg is None:
            return False, 0, ["no k6 summary to compare"]
        ok = reg <= t.get("max_p95_regression_pct", 10)
        return ok, 100 if ok else max(0, 100 - 5 * reg), [] if ok else [f"p95 regressed {reg:.1f}%"]
    return False, 0, [f"unknown check {name}"]


def score(card, gates=None):
    gates = gates or load_gates()
    total_w = acc = 0.0
    failures = []
    for name, t in gates["checks"].items():
        c = card["checks"].setdefault(name, {"status": "skipped", "note": "not run"})
        if c["status"] == "n/a":
            c.update(passed=None, score=None, reasons=[])
            continue
        if c["status"] != "measured":
            passed, sc, reasons = False, 0, [f"{c['status']}: {c.get('note', '')}".strip()]
        else:
            passed, sc, reasons = judge(name, c, t)
        if not t.get("required", True) and not passed and c["status"] != "measured":
            c.update(passed=None, score=None, reasons=reasons + ["optional - excluded"])
            continue
        c.update(passed=passed, score=round(sc, 1), reasons=reasons, required=t.get("required", True))
        w = t.get("weight", 1)
        total_w += w
        acc += w * sc
        if not passed:
            failures.append({"check": name, "required": t.get("required", True), "weight": w, "reasons": reasons})
    overall = round(acc / total_w, 1) if total_w else 0.0
    blockers = [f for f in failures if f["required"]]
    verdict = "PASS" if not blockers and overall >= gates["min_overall_score"] else "FAIL"
    failures.sort(key=lambda f: (not f["required"], -f["weight"]))
    card.update(overall_score=overall, min_overall_score=gates["min_overall_score"],
                verdict=verdict, failures=failures)
    return card


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else forge() / "gates" / "latest.json"
    card = read_json(path) or sys.exit(f"no scorecard at {path}")
    score(card)
    write_json(path, card)
    it = card.get("iteration_dir")
    if it:
        write_json(f"{it}/scorecard.json", card)
    print(f"VERDICT {card['verdict']}  overall {card['overall_score']} (min {card['min_overall_score']})")
    for f in card["failures"]:
        print(f"  {'BLOCKER' if f['required'] else 'warn   '} {f['check']}: {'; '.join(f['reasons'])}")
    sys.exit(0 if card["verdict"] == "PASS" else 2)


if __name__ == "__main__":
    main()
