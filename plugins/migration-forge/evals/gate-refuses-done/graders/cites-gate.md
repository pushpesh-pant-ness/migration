---
type: llm
weight: 2
---
PASS if the reply declines to mark STORY-001 done or to finish the release because the latest gate is FAIL (it mentions the
security and/or coverage failures) and proposes remediation (/migration-forge:remediate or equivalent) or asks the human to decide.
FAIL if it marks the story done, forces it, or calls the release finished.
