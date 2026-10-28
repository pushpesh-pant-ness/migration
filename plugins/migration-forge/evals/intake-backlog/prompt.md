---
max_turns: 40
timeout_seconds: 900
runs: 2
allowed_tools: [Read, Write, Edit, Glob, Grep, Bash, Skill, Agent, AskUserQuestion]
---

Use ./work as the migration workspace. Our story: "Customers complain the shop is slow and insecure. We must move the shop
(./legacy-shop-src, Express + jQuery + MySQL 5.7) to a supported stack without changing how quotes, order listing and
cancellation behave, with at most 30 minutes downtime." For now only create the epic and child stories with acceptance
criteria locally (we have no Jira access) - do not start discovery. If you need answers, make reasonable assumptions and label them.
