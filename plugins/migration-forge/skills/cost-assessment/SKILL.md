---
description: Method for the migration cost gate - Claude token spend from transcripts, pilot-based projection, Infracost for IaC, and levers to cut cost without cutting verification. Use when estimating, reporting or gating migration cost.
user-invocable: false
---

# Cost assessment

## Producing the cost report (done by the main conversation, no subagent)
1. Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" cost_estimate.py --out forge/cost.json`.
2. Write `forge/decisions/cost-report.md` with:
   - spend to date
   - the projection (formula below, with its assumptions)
   - the budget (`checks.cost.max_tokens`)
   - infra cost, legacy vs target (Infracost; otherwise a sizing table labeled ESTIMATE, using pricing-page URLs fetched today)
   - the top 3 cost levers
3. Report 5 lines: the numbers and one recommendation.

## What is measured, and how
- **Token spend:** `cost_estimate.py` sums `usage` from this workspace's Claude Code transcripts (`~/.claude/projects/<encoded-path>/**/*.jsonl`) since `state.started_at`, deduplicated by message id. Subagent and workflow transcripts are included because they sit under the same project directory.
  - The budget figure, `tokens_total`, is input + output + cache_creation.
  - Cache reads are reported separately. They are cheap and would distort a budget.
- **USD for tokens:** only when the human sets `cost.usd_per_mtok` in `forge/gates.json`. Prices change and differ by model and plan, so they are never hardcoded.
- **Infra:** Infracost on `*.tf` in the legacy and modernized trees. It needs `infracost auth login`. Without IaC, the infra cost is reported as an ESTIMATE and not gated.

## Projection (plan time and after the pilot)
```
projected_total = spent_so_far + (pilot_tokens / pilot_points) * remaining_points * 1.3
```
The 1.3 covers remediation and re-gating overhead. Before the pilot, give a range using 0.5× to 2× a reference rate. Label it low-confidence.

## Budget gate
- `checks.cost.max_tokens`: 0 means no limit. The script compares `tokens_total` against it.
- `max_monthly_usd` and `max_monthly_increase_pct` apply to Infracost figures only.

## Levers, ordered by impact without losing quality
1. **Scope:** pilot first, and migrate by wave. Don't re-run discovery on unchanged modules.
2. **Model per stage:** mechanical stages (tracker updates, cost reports, bulk renames) can use a smaller model. Keep the strongest model for the stages that cost most when they go wrong: business-rule extraction, the gatekeeper, and security review.
3. **Parallelism:** a wider fan-out gives faster results, not cheaper ones. Cap waves at the number of truly independent modules.
4. **Context hygiene:** agents read `analysis/` summaries, not whole legacy trees. Use `--only` on run_gates while iterating locally, but always run a full gate before marking anything done.
5. **Never** save cost by skipping verification, security scans, or evals.
