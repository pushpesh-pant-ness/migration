---
description: How to design behavioral evals that prove a migrated system matches legacy - golden-master HTTP diffs, SQL result diffs and story acceptance tests in forge/evals/cases.json, run by evals_run.py - with coverage rules and an edge-case catalogue. Use when writing or reviewing migration eval cases or acceptance tests.
user-invocable: false
---

# Migration evals

## Case file: `forge/evals/cases.json`
```json
{"cases": [
  {"id":"EV-001","story":"STORY-004","rule":"BR-12","priority":"P0","type":"http_diff",
   "request":{"method":"POST","path":"/api/orders/quote","headers":{"Authorization":"Bearer ${TEST_TOKEN}"},
              "body":{"items":[{"sku":"A1","qty":3}],"coupon":"SPRING"}},
   "ignore":["quoteId","createdAt"], "why_ignored":"generated per request"},
  {"id":"EV-002","story":"STORY-009","rule":"BR-30","priority":"P0","type":"sql_diff",
   "query":"SELECT status, COUNT(*), SUM(total) FROM orders GROUP BY status",
   "target_query":"SELECT status, COUNT(*), SUM(total_amount) FROM orders GROUP BY status"},
  {"id":"EV-003","story":"STORY-004","priority":"P0","type":"command",
   "command":"npx jest -t \"STORY-004\"","cwd":"modernized/shop-web"}
]}
```
An **expected-behavior** case (`http_expect`) checks the new app against stated values instead of legacy output. Use it for behavior that changes on purpose, where legacy is the bug and parity can't express it: security fixes, PII rules, new validation, and contract rules from the story.
```json
{"id":"EV-030","story":"STORY-007","rule":"PII-1","priority":"P0","type":"http_expect","service":"patient-service",
 "request":{"method":"GET","path":"/patients"},
 "expect":{"status":200,"json":{"*.ssn":{"absent":true},"0.id":{"exists":true}},"max_ms":800}},
{"id":"EV-031","story":"STORY-007","priority":"P0","type":"http_expect","mutates":true,
 "request":{"method":"POST","path":"/patients","body":{"name":"Eval","email":"eval@example.com"}},
 "expect":{"status":201,"json":{"id":{"exists":true}}},"save":{"new_id":"id"}},
{"id":"EV-032","story":"STORY-007","priority":"P1","type":"http_expect",
 "request":{"path":"/patients/{{new_id}}"},"expect":{"status":200,"json":{"name":"Eval"}}}
```
- **json operators:** equals, `exists`, `absent`, `type`, `min_len`, `contains`, `gt`, `regex`.
- **Paths:** `0.id` checks the first item only. `*.ssn` checks **every** item, and fails when the list is empty.
- **Chaining:** `save` values are available to later cases as `{{name}}`. Cases run in file order, so a chained case also needs its `save` case when you use `--only`.
- **Baseline:** `evals_run.py --against legacy` runs only the `http_expect` cases on legacy into `results-legacy.json`. That file is for the before/after report, not the gate.
- **Multi-service systems:** `"service": "<name>"` takes its legacy and new URLs from `forge/env/env.json` → `"services": {"<name>": {"legacy": "...", "new": "..."}}`. This works for `http_diff` too.

A UI case looks like this:
```json
{"id":"EV-020","story":"STORY-002","priority":"P0","type":"ui_e2e","spec":"orders.spec.ts","grep":"STORY-002","visual":true,"mutates":false}
```
Run with `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" evals_run.py`.
- **App URLs** come from `forge/env/env.json`, which `/migration-forge:env` creates. `FORGE_LEGACY_URL` and `FORGE_NEW_URL` override them.
- **sql_diff** needs `FORGE_SOURCE_DB_URL` and `FORGE_TARGET_DB_URL`, and is used only on the DB track.
- **`"mutates": true`** makes evals_run reset the seeded data first, so both apps start from the same state.

## UI parity (`ui_e2e`)
1. **Setup, once.** Copy `${CLAUDE_PLUGIN_ROOT}/skills/migration-evals/assets/ui/` to `forge/evals/ui/`. Then run `npm install && npx playwright install chromium` there.
2. **Write specs** in `forge/evals/ui/specs/`, one per user flow, with tests named `<STORY-ID> <flow>`. To explore the legacy UI while writing locators, the `playwright` plugin from claude-plugins-official gives you a browser MCP.
3. **How a case passes.** The runner executes each spec against **legacy first**. If it fails there, the case is marked INVALID, because a parity test must describe current behavior. Then it runs against the new app.
   - `visual: true` records the golden screenshots from legacy and compares the new app's screenshots to them.
4. **Locators.** Use user-facing ones: role, label, visible text. Selectors tied to a framework break by design during a migration.
5. **Coverage.** Every user-facing flow in a P0 or P1 story gets at least one `ui_e2e` case. Give each P0 screen `visual: true` unless the story deliberately redesigns it. In that case, record the accepted redesign in the ticket.

Header values expand `${ENV_VAR}` at run time, so secrets such as test tokens stay in the environment and never in the file.

## Coverage rules. These feed the behavior gate.
1. Every P0 business rule gets at least 2 cases: a happy path plus a boundary or negative case.
2. Every acceptance criterion gets at least 1 case. Name the acceptance tests after the story id so `command` cases can select them.
3. Every endpoint group gets http_diff golden masters built from realistic fixtures. **No production PII.** Synthesize the data, or mask it.
4. Every report or aggregate query, and every stored procedure being moved into code, gets an sql_diff.
5. `ignore` is allowed only for truly nondeterministic fields, and each one needs a `why_ignored`.
5a. Every behavior a story changes on purpose gets an `http_expect` case instead of an `ignore` on the parity case. That covers every security fix (injection answered with 400/404, auth failures) and every PII rule (`*.<field>` absent). Every P0 security or PII rule needs at least one.
6. The `coverage.md` matrix lists rule/AC → case ids, and every gap is listed explicitly.

## Edge-case catalogue
Pick the ones that apply to each rule.
- **Money:** rounding mode (half-even vs half-up), currency scale, negative amounts, very large values, sums over many rows.
- **Time:** DST transitions, UTC vs local, end of month/leap day, time-zone-less timestamps, the server tz differing from the DB tz.
- **Text:** unicode/emoji, accents, case-insensitive matching that legacy relied on, trailing spaces (CHAR), empty string vs NULL, max length.
- **Numbers:** zero, negatives, integer overflow at legacy column limits, float vs decimal.
- **Collections:** empty, one item, the pagination boundary (page size ±1), sort stability on ties.
- **Auth:** missing or expired token, wrong role, another tenant's id (IDOR), CSRF on state-changing forms.
- **Concurrency:** double submit or idempotency keys, optimistic locking conflicts.
- **Errors:** validation messages and status codes, which legacy clients may parse, and timeouts on downstream calls.
- **Data:** legacy "dirty" rows (zero dates, orphan FKs, out-of-range enums) that the migration must preserve or map.

## Anti-patterns. The gatekeeper rejects these.
- Cases that can't fail: no assertion, or an assertion that equals itself.
- Asserting implementation details such as SQL text or internal method calls.
- Golden masters recorded from the **new** system.
- `ignore: ["*"]`, or ignoring whole bodies.
