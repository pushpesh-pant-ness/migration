---
description: Nightly end-to-end pilot on the legacy-shop fixture (expensive; needs the plugin's dependencies installed and Docker)
max_turns: 200
timeout_seconds: 3600
runs: 1
env:
  EVAL_FORGE_AUTO_APPROVE: "1"
allowed_tools: [Read, Write, Edit, MultiEdit, Glob, Grep, Bash, Skill, Agent, WebFetch, WebSearch]
---

Use ./work as the migration workspace and run a pilot migration of ./legacy-shop-src.
Story: "Move the shop off EOL Node/Express 4.16/jQuery 1.12 to a supported Node LTS + TypeScript backend and a modern
frontend, remove the SQL injection, XSS and hardcoded credentials, and keep quote (BR-1), order listing (BR-2) and
cancellation (BR-3) behaving exactly as today. Keep the existing MySQL database unchanged."
This message is my approval for every checkpoint (backlog, stack, migration) - record each approval with --by "eval".
Pilot only: migrate the quote module (BR-1) end to end, then run the gate once and remediate at most once.
Finish with the gate verdict and its blockers; do not continue to further waves.
