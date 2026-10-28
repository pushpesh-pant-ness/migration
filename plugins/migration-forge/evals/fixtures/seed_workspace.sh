#!/usr/bin/env bash
# Usage: seed_workspace.sh <phase> [verdict]
# Builds a minimal forge workspace in $PWD from static files (no Python needed in the scaffold).
set -e
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
phase="$1"
verdict="${2:-}"
mkdir -p legacy forge/tracker/stories forge/tracker/epics forge/gates/iteration-1 modernized/shop
cp -r "$here/legacy-shop" legacy/shop

cat > forge/state.json <<JSON
{"name":"shop","repo":null,"legacy":"legacy/shop","analysis":"analysis/shop","modernized_root":"modernized/shop",
 "target":"react+nestjs+postgresql","phase":"$phase",
 "approvals":{"backlog":{"by":"user"},"stack":{"by":"user"},"migration":{"by":"user"}},
 "iteration":1,"started_at":"2026-01-01T00:00:00+00:00","history":[],
 "gate_history":[{"iteration":1,"verdict":"${verdict:-PASS}","overall":62.0}]}
JSON

cat > forge/tracker/tracker.json <<'JSON'
{"version":1,"counters":{"EPIC":1,"STORY":2},"items":{
 "EPIC-001":{"id":"EPIC-001","type":"epic","title":"Modernize shop","status":"in-progress","priority":"P0","points":null,"parent":null,"labels":[],"blocked_by":[],"modules":[],"created":"2026-01-01T00:00:00+00:00","updated":"2026-01-01T00:00:00+00:00"},
 "STORY-001":{"id":"STORY-001","type":"story","title":"Migrate order quote (BR-1)","status":"review","priority":"P0","points":3,"parent":"EPIC-001","labels":["backend"],"blocked_by":[],"modules":["orders"],"created":"2026-01-01T00:00:00+00:00","updated":"2026-01-01T00:00:00+00:00"},
 "STORY-002":{"id":"STORY-002","type":"story","title":"Migrate order list (BR-2)","status":"backlog","priority":"P1","points":5,"parent":"EPIC-001","labels":["frontend","backend"],"blocked_by":["STORY-001"],"modules":["orders"],"created":"2026-01-01T00:00:00+00:00","updated":"2026-01-01T00:00:00+00:00"}}}
JSON

for id in STORY-001 STORY-002; do
  {
    printf -- '---\nid: "%s"\ntype: "story"\n---\n# %s\n\n## Description\nSee tracker.json.\n\n' "$id" "$id"
    printf -- '## Acceptance criteria\n- [ ] Given a cart over 100 with coupon SPRING When quoted Then total equals legacy quote (BR-1)\n'
    printf -- '- [ ] Given an empty cart When quoted Then 400 like legacy\n\n'
    printf -- '## Definition of done\n- [ ] Latest gate scorecard PASS for the modules touched\n\n## Notes\n'
  } > "forge/tracker/stories/$id.md"
done
printf -- '---\nid: "EPIC-001"\ntype: "epic"\n---\n# EPIC-001: Modernize shop\n' > forge/tracker/epics/EPIC-001.md

if [ -n "$verdict" ]; then
  cat > forge/gates/latest.json <<JSON
{"iteration":1,"verdict":"$verdict","overall_score":62.0,"min_overall_score":85,
 "failures":[{"check":"security","required":true,"weight":3,"reasons":["2 high finding(s) > 0"]},
             {"check":"coverage","required":true,"weight":2,"reasons":["line coverage 61.0% < 80%"]}],
 "checks":{}}
JSON
  cp forge/gates/latest.json forge/gates/iteration-1/scorecard.json
fi
