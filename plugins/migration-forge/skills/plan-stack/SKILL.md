---
description: Choose the target tech stack for a migration with pinned, currently supported versions, compatibility matrix and scored options, recorded as ADR-001 for human approval. Use after discovery or when the user asks what stack/versions to migrate to.
argument-hint: [optional preference, e.g. "prefer postgres" or "stay on angular"]
---

# Plan the target stack

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

1. Run `F state.py phase plan-stack`.
2. Delegate to the `stack-researcher` agent. The prompt should name the run, the constraints from `forge/story.md`, the user's preference (`$ARGUMENTS`), and the target hint in state.
3. **Verify before presenting.** Open `forge/decisions/ADR-001-target-stack.md` and check that:
   - every pinned version has a source URL
   - no row is UNVERIFIED (if one is, re-fetch it or flag it to the human)
   - the compatibility matrix covers DB driver ↔ DB server
   - `forge/decisions/target-stack.json` exists
4. Run `F state.py set target '"<one-line stack summary>"'`.
5. Run the **approve stack** checkpoint. Show the decision table, the top 3 risks, and the rejected options in one line each.
