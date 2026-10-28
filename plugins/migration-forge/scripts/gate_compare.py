#!/usr/bin/env python3
"""Before/after report: the legacy baseline (run_gates.py --baseline) vs a gate iteration.

  gate_compare.py [--after forge/gates/latest.json]     -> forge/gates/comparison.md + comparison.json

Every numeric metric both scorecards share is listed with its delta. Direction comes from the threshold
(max_* -> lower is better, min_* -> higher is better); metrics without a threshold are shown as info.
Also folds in the http_expect pass rate on legacy (forge/evals/results-legacy.json) vs new (results.json).
"""
import argparse
import sys

from forgelib import forge, load_gates, read_json, write_json


def rows(before, after, gates):
    out = []
    for name, ca in after.get("checks", {}).items():
        cb = before.get("checks", {}).get(name)
        if not cb:
            continue
        t = gates["checks"].get(name, {})
        for metric, va in (ca.get("metrics") or {}).items():
            vb = (cb.get("metrics") or {}).get(metric)
            if isinstance(va, bool) or isinstance(vb, bool) or not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
                continue
            rule = next(((k, t[k]) for k in (f"max_{metric}", f"min_{metric}") if t.get(k) is not None), None)
            d = round(va - vb, 4)
            verdict = "info" if not rule else "same" if d == 0 else \
                ("improved" if (d < 0) == rule[0].startswith("max_") else "REGRESSED")
            out.append({"check": name, "metric": metric, "before": vb, "after": va, "delta": d, "verdict": verdict,
                        "threshold": f"{rule[0][:3]} {rule[1]}" if rule else ""})
    return out


def expect_rate(path):
    cases = [c for c in (read_json(path, {}) or {}).get("cases", []) if c.get("type") == "http_expect"]
    return (round(100 * sum(c["passed"] for c in cases) / len(cases), 1), len(cases)) if cases else (None, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--after", default=str(forge() / "gates" / "latest.json"))
    a = ap.parse_args()
    before = read_json(forge() / "gates" / "baseline" / "scorecard.json") or \
        sys.exit("no baseline: run `run_gates.py --baseline` on the legacy code first")
    after = read_json(a.after) or sys.exit(f"no scorecard at {a.after}")
    r = rows(before, after, load_gates())
    eb, nb = expect_rate(forge() / "evals" / "results-legacy.json")
    ea, na = expect_rate(forge() / "evals" / "results.json")
    md = [f"# Modernization report: legacy baseline vs iteration {after.get('iteration')}", "",
          f"Overall score: {before.get('overall_score')} -> {after.get('overall_score')} "
          f"(gate verdict now: **{after.get('verdict')}**)", "",
          "| Check | Metric | Legacy | Now | Change | Verdict | Threshold |", "|---|---|---|---|---|---|---|"]
    md += [f"| {x['check']} | {x['metric']} | {x['before']:g} | {x['after']:g} | {x['delta']:+g} | {x['verdict']} | {x['threshold']} |"
           for x in r]
    if eb is not None or ea is not None:
        md += ["", f"Expected-behavior evals (http_expect): legacy {eb}% of {nb} -> new {ea}% of {na}"]
    imp, reg = sum(x["verdict"] == "improved" for x in r), [x for x in r if x["verdict"] == "REGRESSED"]
    md += ["", f"**Improved: {imp} - Regressed: {len(reg)}**" + (": " + ", ".join(f"{x['check']}.{x['metric']}" for x in reg) if reg else "")]
    (forge() / "gates" / "comparison.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    write_json(forge() / "gates" / "comparison.json", {"rows": r, "http_expect": {"legacy_pct": eb, "new_pct": ea}})
    print("\n".join(md))


if __name__ == "__main__":
    main()
