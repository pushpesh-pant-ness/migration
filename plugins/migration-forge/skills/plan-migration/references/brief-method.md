# Modernization brief (built in, tool-neutral)

`analysis/<name>/MODERNIZATION_BRIEF.md` is the single plan a steering group approves and the build follows. Nothing is built until the human approves it (the **approve migration** checkpoint).

Read `ASSESSMENT.md`, `topology.json`, `BUSINESS_RULES.md` (with the review answers), `forge/decisions/ADR-001-target-stack.md` and `forge/story.md`. The ADR is the source for versions; the brief never pins a version the ADR doesn't.

## Sections
1. **Goal and scope:** the business outcome from the story, what is in, what is explicitly out.
2. **Target stack:** one line per layer, with the ADR's pinned versions.
3. **Track per layer and module:** uplift, transform or reimagine (see `skills/execute/references/build-tracks.md`), with the reason from the assessment.
4. **Phases:** the waves from `forge/decisions/plan.md`. For each phase: modules, entry criteria, exit criteria (tests green, P0 rules covered, Jenkins gate PASS), and the rollback.
5. **Coexistence and cutover:** how old and new run side by side (route-by-route proxy, feature flags), and how traffic and data move over. With the DB track off: "DB unchanged", and the ORM/driver settings that map the existing schema.
6. **Proof strategy:** characterization tests from legacy behavior, old-vs-new comparison on the same inputs, P0 rule → test mapping, and what the `verify` skill will check.
7. **Risks:** top 5, each with an owner and a mitigation.
8. **Decisions needed from the human:** anything the brief cannot settle alone.

Keep it under about three pages. Link to the other files rather than copying them.
