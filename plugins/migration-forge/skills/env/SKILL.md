---
description: Provision and control the side-by-side runtime (legacy app + modernized app, each on identically seeded synthetic data) that golden-master and UI parity evals run against. Use before behavior evals, when evals report the apps are unreachable, or when the user asks to run/start/stop/reset the legacy and new apps.
argument-hint: [setup | up | reset | status | down]
---

`E` = `bash "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" env.py`

- **setup**, or the default when `forge/env/env.json` is missing: delegate to the `env-provisioner` agent. Then run `E up`.
- **up / reset / status / down:** run `E <cmd>` and show the result.

## Rules
- `evals_run.py` reads the URLs from `forge/env/env.json` automatically, and environment variables override them. It runs `env.py reset` before any case marked `"mutates": true`.
- The env must be **up and healthy** before `/migration-forge:gate` runs evals. The gate skill checks this with `E status`.
- When the modernized code changes, run `E up` again. It rebuilds the `new` service. Never rebuild `legacy` from changed sources: legacy is frozen.
- `E down` when the run is finished or paused. It removes the containers and the seeded volumes.
