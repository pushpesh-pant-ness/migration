# Target-stack research method

## 1. Constraints first (hard filters)
Apply these before scoring. Any option that violates one is out:
- org catalog (`config/stack-catalog.json`)
- hosting and cloud
- compliance
- team skills named in the story
- licence policy
- must-keep integrations
- downtime budget, which affects whether the DB engine can change

## 2. Version pinning. The procedure for each component:
1. `WebFetch https://endoflife.date/api/<product>.json`. Pick the newest cycle that matches `version_policy`: LTS if one exists, released at least 60 days ago, and with at least 18 months of support left. Record `latest` (the patch), `releaseDate`, `eol`/`support`, and the URL.
2. Context7: resolve the library, then fetch its "upgrade"/"migration" docs from the source major to the target major. Record the breaking changes.
3. Peer compatibility: the framework's supported runtime range, the ORM's supported DB versions, and the DB driver ↔ server. Each needs a doc link.
4. If a component is not on endoflife.date, use its official releases page (GitHub releases, vendor lifecycle page).

## 3. Scoring (weights default; change only with a reason in the ADR)
| Criterion | Weight | 1 = | 5 = |
|-----------|--------|-----|-----|
| Fit to story & constraints | 0.20 | partial | complete |
| Migration effort (from current stack) | 0.20 | rewrite | mechanical/codemods exist |
| Risk (breaking changes, data model change) | 0.15 | high | low |
| Support window | 0.10 | <18 mo | >36 mo |
| Ecosystem & tooling (codemods, OpenRewrite, Rector, ng update) | 0.10 | thin | rich |
| Team skill | 0.10 | new | known |
| Run cost | 0.10 | higher | lower |
| Security posture (defaults, CVE history) | 0.05 | weak | strong |

## 4. ADR template (`forge/decisions/ADR-001-target-stack.md`)
```markdown
# ADR-001: Target stack for <name>
Status: Proposed   Date: <today>   Deciders: <human approver>
## Context
<current stack with versions + EOL (from current-stack.md), constraints, story goals>
## Options considered
### Option A — <frontend / backend / DB / ORM+migrations / tests>
<score table row + 3 bullets pros/cons>
### Option B …
## Decision
<Option X> because <2–3 sentences tied to scores>.
### Pinned versions
| Component | Version | Released | EOL | Source |
## Compatibility matrix
| Pair | Supported? | Evidence |
## Breaking-change digest (source major → target major)
- <component>: <change> — <link>
## Migration track per layer
frontend: uplift | transform | reimagine — backend: … — DB: in-place | expand/contract | cross-engine
## Consequences
## Rejected options
```
Each layer's track feeds `/code-modernization:modernize-brief`:
- **uplift:** same framework, newer version
- **transform:** different framework, same behavior
- **reimagine:** a redesign
