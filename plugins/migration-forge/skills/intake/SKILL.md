---
name: intake
description: Turn a migration story into a local Jira-style backlog (epic, child stories, tasks, acceptance criteria, definition of done, dependency links, per-phase checklists) under forge/tracker/. Use when the user gives a story/requirement for a migration or asks to create epics, stories or Jira tickets locally.
argument-hint: [story.md | "story text"]
---

# Intake: story → backlog

`forge` = `"<forge-root>/bin/forge"` (Windows shells: `bin\forge.cmd`). `<forge-root>` is this toolkit's folder: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, otherwise `$FORGE_ROOT` (see `AGENTS.md`).

1. **Make sure the run exists.** If `forge/state.json` is missing, run the setup in the `migrate` skill, step 0, first. If the arguments (`$ARGUMENTS`) name a different story, copy it to `forge/story.md`.
2. **Clarify only what blocks a backlog.** Ask at most 5 questions, and only if the story leaves them open:
   - target platform or hosting constraints
   - deadline or downtime budget
   - compliance (PII, PCI, HIPAA)
   - must-keep integrations
   - features explicitly dropped

   If the user doesn't know an answer, or nobody is there to ask (an unattended run), record it as an `assumption`.
3. **Delegate to the `story-analyst` role** (`<forge-root>/agents/story-analyst.md`; intake pass) with this prompt: "Intake pass for run <name>. Story at forge/story.md. Answers: <…>."
4. **Check the result yourself.** Run `forge tracker validate`. It must exit 0. Then run `forge tracker board` and read `forge/tracker/board.md`.
5. **Checklists.** `forge tracker init` copies the templates from `<forge-root>/skills/intake/assets/checklists/` into `forge/tracker/checklists/`. Tailor `discovery.md` to the stack that is visible in the repo.
6. **Present** the epic, the stories grouped by priority, the critical path, and the open questions. Then run the **approve backlog** checkpoint (see the `migrate` skill).

The backlog is refined again after discovery. That pass adds module stories and real dependencies, so at intake keep the stories business-level plus the standard foundation stories.
