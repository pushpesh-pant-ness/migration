# Build tracks (built in, tool-neutral)

How one ticket is built for each track in the brief. If your tool has its own modernization build commands (for example Anthropic's `code-modernization` plugin in Claude Code: `modernize-uplift`, `modernize-transform`, `modernize-reimagine`), you may use them instead, scoped to the ticket's modules.

## Rules for every track
- New code goes only under `modernized/`. `legacy/` is read-only; build or run legacy only in a disposable copy (`scratch/`).
- Tests come first and are named after the ticket id, so `-t "STORY-004"` or `-k STORY_004` selects them.
- Every P0 business rule the ticket carries (`BR-*` ids in the ticket) is named by at least one test that runs.
- Don't weaken, skip or delete tests, and don't add scanner suppressions, to get green.
- Write what you learned (surprises, deltas, decisions) to `analysis/<name>/BUILD_NOTES.md`, one dated section per ticket.

## uplift: same technology, newer version
1. **Delta catalog.** From the official upgrade guides between the source and target versions (linked in the ADR), list the breaking changes. Then search the code for each one and keep only the ones this code actually hits, with file:line. Write it to `analysis/<name>/DELTA_CATALOG.md`.
2. If the catalog shows most of the code would be rewritten, stop and tell the human: this is a transform, not an uplift.
3. **Pilot unit first:** copy one unit into `modernized/`, move it to the target version, fix only the catalog entries, and run its existing tests on both versions. Record the lessons before the next unit.
4. The proof is the same test suite passing on the old and the new version, with the same counts.

## transform: rewrite a module in a new technology
1. **Pin legacy behavior.** Write characterization tests against the legacy module: run it (in the disposable copy) on representative inputs, including boundaries, and save the outputs as golden files under `modernized/<name>/tests/golden/<module>/`.
2. **Rewrite** the module idiomatically in the target stack under `modernized/<name>/<module>/`. Keep its external contract (routes, payloads, status codes) unless a story says otherwise.
3. **Compare old and new** on the same inputs with a script, byte for byte. Mask only fields that must vary (timestamps, generated ids) and list every masked field in the test. Every difference is either fixed or written down for the human to accept.

## reimagine: rebuild on a new architecture
1. **Spec from the code:** capabilities, the BR cards they carry, and the data each needs, in `analysis/<name>/SPEC.md`.
2. **Architecture:** services, boundaries, data ownership and integration, in `analysis/<name>/ARCHITECTURE.md`. A human reviews and approves it before scaffolding (ask; don't assume).
3. **Scaffold** each service with executable acceptance tests derived from the BR cards, then build to green.
