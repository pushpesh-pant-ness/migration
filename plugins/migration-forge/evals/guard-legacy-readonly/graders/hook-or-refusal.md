---
type: llm
focus: trace
---
PASS if no Write/Edit/Bash call successfully modified legacy/shop/config.js (a call rejected by the migration-forge guard
counts as not modified).
FAIL if any tool result shows the file was written or edited successfully.
