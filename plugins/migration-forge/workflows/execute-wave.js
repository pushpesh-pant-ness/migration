export const meta = {
  name: 'execute-wave',
  description: 'Build one wave of independent migration tickets in parallel git worktrees, then merge and test them sequentially',
  whenToUse: 'Called by /migration-forge:execute for waves after the pilot, with args {name, repo, base_branch, tickets:[{id,title,modules,track,evals}]}',
  phases: [
    { title: 'Build', detail: 'one worktree agent per ticket, test-first' },
    { title: 'Merge', detail: 'sequential merge into the base branch + full test run' },
  ],
}

if (!args || !Array.isArray(args.tickets) || args.tickets.length === 0 || !args.plugin_root) {
  throw new Error('execute-wave needs args {name, repo, base_branch, plugin_root, tickets:[...]}')
}

// Workflow scripts get no ${CLAUDE_PLUGIN_ROOT} substitution, so the calling skill passes it in.
const F = `bash "${args.plugin_root}/scripts/py.sh"`

const BUILD_SCHEMA = {
  type: 'object',
  required: ['id', 'status', 'branch', 'summary'],
  properties: {
    id: { type: 'string' },
    status: { type: 'string', enum: ['built', 'failed'] },
    branch: { type: 'string' },
    evals_passed: { type: 'array', items: { type: 'string' } },
    evals_failed: { type: 'array', items: { type: 'string' } },
    test_command: { type: 'string' },
    summary: { type: 'string' },
  },
}

const MERGE_SCHEMA = {
  type: 'object',
  required: ['results', 'full_tests_exit_code'],
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'outcome'],
        properties: { id: { type: 'string' }, outcome: { type: 'string', enum: ['merged', 'conflict', 'skipped'] }, note: { type: 'string' } },
      },
    },
    full_tests_exit_code: { type: 'number' },
    notes: { type: 'string' },
  },
}

phase('Build')
const built = await parallel(args.tickets.map(t => () =>
  agent(
    `You are implementing migration ticket ${t.id} ("${t.title}") for run "${args.name}" in an isolated git worktree.
Modules: ${(t.modules || []).join(', ')}. Track: ${t.track}. Eval cases: ${(t.evals || []).join(', ') || 'see forge/evals/cases.json for story ' + t.id}.
Legacy source (READ-ONLY) is at: ${args.repo}. If legacy/${args.name} does not exist in this worktree, create the same link
(POSIX: ln -s "${args.repo}" legacy/${args.name}; Windows: cmd /c mklink /J legacy\\${args.name} "${args.repo}"). Never write into it.
Steps:
1. git switch -c forge/${t.id}
2. Run ${F} evals_run.py --only <this ticket's EV ids> and confirm they fail first.
3. Build with the ${t.track} track: invoke /code-modernization:modernize-${t.track === 'uplift' ? 'uplift' : t.track === 'reimagine' ? 'reimagine' : 'transform'} via the Skill tool, scoped to ${(t.modules || []).join(', ')} only. Do not touch other modules.
4. Make the eval cases and the project tests for these modules pass. Do not weaken or skip tests and do not add suppressions.
5. Do NOT run tracker.py move or run_gates.py (the orchestrator does that). Commit: git add -A && git commit -m "forge(${t.id}): ${t.title}".
Return status built only if the eval cases for this ticket pass.`,
    { label: `build ${t.id}`, phase: 'Build', isolation: 'worktree', schema: BUILD_SCHEMA }
  )
))

const ok = built.filter(b => b && b.status === 'built')
const failed = args.tickets.filter(t => !ok.find(b => b.id === t.id)).map(t => t.id)
log(`built ${ok.length}/${args.tickets.length}` + (failed.length ? `; not built: ${failed.join(', ')}` : ''))

if (ok.length === 0) {
  return { merged: [], failed, conflicts: [], built }
}

phase('Merge')
const merge = await agent(
  `Merge these branches one at a time into ${args.base_branch} in the main workspace (not a worktree), in this order:
${ok.map(b => `- ${b.branch} (${b.id})`).join('\n')}
For each: git merge --no-ff <branch>. If a conflict touches only generated files or lockfiles, resolve it and continue.
If it touches source logic, git merge --abort, mark that ticket "conflict", and continue with the next branch.
After all merges, run the full project test suite of the modernized code once and report its exit code.
Then run: ${F} evals_run.py  (all cases) and include its pass count in notes. Do not run run_gates.py or tracker.py.`,
  { label: 'merge wave', phase: 'Merge', schema: MERGE_SCHEMA }
)

const merged = (merge?.results || []).filter(r => r.outcome === 'merged').map(r => r.id)
const conflicts = (merge?.results || []).filter(r => r.outcome === 'conflict').map(r => r.id)
return { merged, conflicts, failed, full_tests_exit_code: merge?.full_tests_exit_code, notes: merge?.notes, built }
