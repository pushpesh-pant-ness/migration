# Discovery checklist
- [ ] Preflight passed (`analysis/<name>/PREFLIGHT.md`): repo builds or the failure is understood, and the toolchain is identified
- [ ] ASSESSMENT.md: languages, frameworks + versions, LOC per module, test coverage baseline, EOL components
- [ ] topology.json / TOPOLOGY.html: modules, entry points (routes, jobs, queues), external integrations
- [ ] BUSINESS_RULES.md: P0 rules have ids (BR-*) and source locations, and are reviewed by a human (modernize-review)
- [ ] C4 context + container diagrams (`forge/decisions/c4/`)
- [ ] DB: if the DB track is on, write the inventory (`forge/db/inventory.md`). If it is off, record the existing DB engine and version for driver/ORM compatibility
- [ ] Secrets found are listed in SECRETS.local.md only (gitignored), never in tickets
- [ ] Each module is mapped to at least one story; dependencies are recorded as blocked_by
- [ ] Characterization-test strategy chosen (HTTP golden master / SQL diff / unit)
