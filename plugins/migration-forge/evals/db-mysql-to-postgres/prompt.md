---
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
---

We're moving a MySQL 5.7 database (lax sql_mode) to PostgreSQL. It has TINYINT(1) flags, DATETIME columns with some
'0000-00-00 00:00:00' values, an ENUM status column and ON UPDATE CURRENT_TIMESTAMP. How should we handle those, and
how do we prove no data was lost?
