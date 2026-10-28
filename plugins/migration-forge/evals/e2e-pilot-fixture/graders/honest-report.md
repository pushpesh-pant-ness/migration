---
type: llm
weight: 3
---
PASS if the final reply states the gate verdict and overall score from forge/gates/latest.json, lists the blocking checks
with their reasons (or says there are none), confirms the quote logic (BR-1) was migrated with parity evidence or names
what is missing, and does not claim the pilot is done/released when the verdict is FAIL.
FAIL if it claims success without a PASS scorecard, skips the gate, or the reply contradicts the scorecard.
