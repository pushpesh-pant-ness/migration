---
name: verify
description: Prove the modernized code behaves like the legacy - an independent clean re-run of the tests, old-vs-new comparison on the same and on new inputs, a canary break, P0 rule coverage and an untouched legacy tree - with one verdict per module in VERIFICATION.md, then the Jenkins gate. Use after the build waves are done, or when the user asks whether the migration is proven.
argument-hint: [module]
---

# Verify

`forge` = `"<forge-root>/bin/forge"` (Windows shells: `bin\forge.cmd`). `<forge-root>` is this toolkit's folder: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, otherwise `$FORGE_ROOT` (see `AGENTS.md`).

Run `forge state phase verify`. Do this in a fresh context if you can (a new session or a subagent): what the build left behind is a claim, and this skill re-checks it instead of trusting it. If your tool has its own verification command for modernizations (for example `code-modernization:modernize-verify` in Claude Code), you may use it, as long as it writes the same file.

## Checks, per module (`$ARGUMENTS` limits it to one)
1. **Tests from clean.** Delete build output, run the full suite, and take the counts from the runner's own output or result files. A run that executed no tests, or skipped them, fails this check.
2. **Old vs new on the same inputs.** Re-run the golden-file comparison from the transform track (`skills/execute/references/build-tracks.md`). Every masked field is listed. Every difference is either fixed or accepted by the human, with the reason.
3. **New inputs.** Invent at least 10 inputs nobody used yet (boundaries, empty, huge, unusual order, malformed) and compare old and new again. Where the legacy can't run here, compare with recorded outputs. Then the best possible verdict is PARTLY PROVEN.
4. **Tests that can fail.** Make a deliberate one-line break in the new code (the canary). Tests must turn red. Revert it and confirm green again.
5. **P0 coverage.** Each P0 `BR-*` rule in `BUSINESS_RULES.md` is named by a test that ran and passed. A rule named only by a skipped or pending test is "named, not run".
6. **Legacy untouched.** `forge guard legacy` exits 0.

## Verdict, by fixed rules
- **PROVEN:** all six checks pass.
- **PARTLY PROVEN:** nothing fails, but something could not run (say what is missing).
- **NOT PROVEN:** any test fails, any unaccepted difference, a canary that stayed green, or no tests ran.

Write `analysis/<name>/VERIFICATION.md`: a table of module | verdict | each check with its evidence (command + exit code, counts, file paths), then accepted differences and open items. Never tick a human decision (accepting a difference, signing off) yourself.

Then commit and follow the `gate` skill: Jenkins runs the gates on this commit. Report the verdict per module and the Jenkins verdict. Next: the `harden` skill.
