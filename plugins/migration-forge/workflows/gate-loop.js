export const meta = {
  name: 'gate-loop',
  description: 'Gate -> gatekeeper audit -> root-cause remediation -> re-gate until PASS, no progress, or the iteration cap',
  whenToUse: 'Called by /migration-forge:remediate auto with args {name, plugin_root, max_iterations}',
  phases: [
    { title: 'Gate', detail: 'collect evidence, run_gates.py, gatekeeper' },
    { title: 'Remediate', detail: 'one remediation-engineer per failing check, sequential' },
  ],
}

if (!args || !args.plugin_root) throw new Error('gate-loop needs args {name, plugin_root, max_iterations}')
const F = `bash "${args.plugin_root}/scripts/py.sh"`
const MAX = args.max_iterations || 3
const ORDER = ['security', 'pii', 'behavior', 'database', 'review', 'static', 'tests', 'typecheck', 'coverage', 'lint', 'cost', 'performance']

const GATE_SCHEMA = {
  type: 'object',
  required: ['iteration', 'verdict', 'overall', 'failures'],
  properties: {
    iteration: { type: 'number' },
    verdict: { type: 'string', enum: ['PASS', 'FAIL'] },
    overall: { type: 'number' },
    failures: { type: 'array', items: { type: 'object', required: ['check', 'reasons'],
      properties: { check: { type: 'string' }, reasons: { type: 'array', items: { type: 'string' } } } } },
  },
}
const KEEPER_SCHEMA = {
  type: 'object',
  required: ['verdict', 'confirmed_failures'],
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'FAIL'] },
    confirmed_failures: { type: 'array', items: { type: 'object', properties: {
      check: { type: 'string' }, evidence: { type: 'string' }, why: { type: 'string' }, fix_hint: { type: 'string' } } } },
    suspicions: { type: 'array', items: { type: 'object', properties: { check: { type: 'string' }, why: { type: 'string' } } } },
    summary: { type: 'string' },
  },
}
const FIX_SCHEMA = {
  type: 'object',
  required: ['items'],
  properties: { items: { type: 'array', items: { type: 'object', required: ['failure', 'status'], properties: {
    failure: { type: 'string' }, status: { type: 'string', enum: ['fixed', 'not_fixed', 'needs_human'] },
    root_cause: { type: 'string' }, verified_by: { type: 'string' } } } } },
}

const history = []
let lastKey = null
for (let i = 1; i <= MAX + 1; i++) {
  phase('Gate')
  const gate = await agent(
    `Follow the /migration-forge:gate skill steps 2-3 for run "${args.name}" (collect claude-security, code review, evals and DB evidence as that skill says, then run ${F} run_gates.py).
Do not remediate. Return the iteration number, verdict, overall score and failures exactly as run_gates.py printed / wrote to forge/gates/latest.json.`,
    { label: `gate #${i}`, phase: 'Gate', schema: GATE_SCHEMA })
  if (!gate) return { verdict: 'ERROR', history, reason: 'gate agent failed' }

  let keeper = null
  if (gate.verdict === 'PASS') {
    keeper = await agent(
      `Audit forge/gates/latest.json (iteration ${gate.iteration}) for run "${args.name}" as the gatekeeper. Write nothing.`,
      { label: `gatekeeper #${i}`, phase: 'Gate', agentType: 'migration-forge:gatekeeper', schema: KEEPER_SCHEMA })
  }
  const fails = [...gate.failures.map(f => ({ check: f.check, why: f.reasons.join('; ') })),
                 ...((keeper && keeper.confirmed_failures) || []).map(f => ({ check: f.check, why: `${f.why} (${f.evidence})` }))]
  history.push({ iteration: gate.iteration, verdict: gate.verdict, overall: gate.overall, gatekeeper: keeper ? keeper.verdict : null, failures: fails.length })
  if (gate.verdict === 'PASS' && keeper && keeper.verdict === 'PASS') return { verdict: 'PASS', history }

  const key = fails.map(f => `${f.check}:${f.why}`).sort().join('|')
  if (key === lastKey) { log('same failures twice in a row - escalating'); return { verdict: 'ESCALATE', reason: 'no progress', history, failures: fails } }
  lastKey = key
  if (i > MAX) break

  phase('Remediate')
  const checks = [...new Set(fails.map(f => f.check))].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b))
  for (const c of checks) {  // sequential: fixes for different checks often touch the same files
    const mine = fails.filter(f => f.check === c)
    const res = await agent(
      `Gate iteration ${gate.iteration} for run "${args.name}" failed check "${c}":\n${mine.map(f => '- ' + f.why).join('\n')}
The exact findings (file:line - rule - message) are in forge/gates/iteration-${gate.iteration}/feedback.md under "## ${c}".
Fix the root causes per your instructions and verify with the underlying tool. Do not run run_gates.py.`,
      { label: `fix ${c} #${i}`, phase: 'Remediate', agentType: 'migration-forge:remediation-engineer', schema: FIX_SCHEMA })
    const human = ((res && res.items) || []).filter(x => x.status === 'needs_human')
    if (human.length) return { verdict: 'NEEDS_HUMAN', questions: human, history }
  }
}
return { verdict: 'ESCALATE', reason: `still failing after ${MAX} remediation iterations`, history }
