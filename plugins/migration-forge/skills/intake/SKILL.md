---
description: Turn a migration story into a local Jira-style backlog (epic, child stories, tasks, acceptance criteria, definition of done, dependency links, per-phase checklists) under forge/tracker/. Use when the user gives a story/requirement for a migration or asks to create epics, stories or Jira tickets locally.
argument-hint: [story.md | "story text"]
---

# Intake: story → backlog

`F` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh"`

1. **Make sure the run exists.** If `forge/state.json` is missing, run the setup in `/migration-forge:migrate` step 0 first. If `$ARGUMENTS` names a different story, copy it to `forge/story.md`.
2. **Clarify only what blocks a backlog.** Ask at most 5 questions, and only if the story leaves them open:
   - target platform or hosting constraints
   - deadline or downtime budget
   - compliance (PII, PCI, HIPAA)
   - must-keep integrations
   - features explicitly dropped

   If the user doesn't know an answer, record it as an `assumption`.
3. **Delegate to the `story-analyst` agent** (intake pass) with this prompt: "Intake pass for run <name>. Story at forge/story.md. Answers: <…>."
4. **Check the result yourself.** Run `F tracker.py validate`. It must exit 0. Then run `F tracker.py board` and read `forge/tracker/board.md`.
5. **Checklists.** `tracker.py init` copies the templates from `${CLAUDE_PLUGIN_ROOT}/skills/intake/assets/checklists/` into `forge/tracker/checklists/`. Tailor `discovery.md` to the stack that is visible in the repo.
6. **Present** the epic, the stories grouped by priority, the critical path, and the open questions. Then run the **approve backlog** checkpoint (see the migrate skill).

The backlog is refined again after discovery. That pass adds module stories and real dependencies, so at intake keep the stories business-level plus the standard foundation stories.
