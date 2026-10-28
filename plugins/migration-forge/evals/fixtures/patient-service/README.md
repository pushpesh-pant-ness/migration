# patient-service fixture (gate smoke test)

A tiny Flask service in two versions, for checking the `static`, `security` and `pii` gate checks and `http_expect`
evals end to end. **All data and secrets here are fake and planted on purpose.**

- `legacy-app/`: deliberate defects: hardcoded password, a leaked token, SSNs/e-mails/phones in seed data, SSN in logs,
  SQL injection, 500 on a missing record, no input validation, `debug=True`, runs as root.
- `modernized-app/`: the same API with those fixed.
- `cases.json`: expected-behavior cases (`http_expect`, service `patient-service`). On the legacy app 5 of 9 pass;
  on the modernized app all 9 pass.

```bash
# from this folder: start one variant on :8080 (both use the same port)
docker compose --profile legacy up -d --build          # or --profile modernized
```
Then in a forge workspace: put `{"services": {"patient-service": {"legacy": "http://localhost:8080", "new": "http://localhost:8080"}}}`
in `forge/env/env.json`, copy `cases.json` to `forge/evals/`, and run
`run_gates.py --baseline --root <this folder>/legacy-app`, `evals_run.py --against legacy`, and so on.

Behind a TLS-inspecting proxy, put your corporate root CA as `corporate-ca.pem` next to each Dockerfile (it is optional
and must not be committed).
