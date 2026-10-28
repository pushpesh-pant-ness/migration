---
type: llm
---
PASS if the answer: checks the actual TINYINT(1) values before mapping to boolean; decides an explicit mapping for zero dates
(e.g. NULL or a sentinel) before copying; maps ENUM to a native enum or CHECK; emulates ON UPDATE with a trigger or app code;
addresses the time zone choice (timestamp vs timestamptz); re-seeds identity sequences; and proves parity with per-table row
counts plus content checksums and a tested down/rollback migration.
FAIL if it suggests a straight dump/restore without these checks, or offers no verification.
