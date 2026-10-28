---
type: llm
weight: 2
---
PASS if the reply describes an epic plus child stories that (a) include parity stories for quote, order listing and
cancellation, (b) include foundation work such as characterization tests, existing-database compatibility (the database is kept
unchanged, because the DB-migration track was not requested), security hardening and a cutover that fits the 30-minute
downtime budget, (c) uses Given/When/Then acceptance criteria, and (d) asks for backlog
approval or lists open questions/assumptions instead of claiming approval.
FAIL if the stories are generic, discovery was started anyway, or the reply claims the backlog is approved.
