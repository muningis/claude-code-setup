import { afterEach, expect, test } from 'bun:test'
import { createHash } from 'node:crypto'
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

const RS_SH = join(import.meta.dir, '..', 'skills', 'ratchet', 'scripts', 'ratchet.sh')
const FIX = join(import.meta.dir, 'fixtures', 'rs')
const EV = '.claude/ratchet/evidence/demo/cp1'
const SHA = /^[0-9a-f]{40,64}$/

// Every test builds its own git repo around a tiny fake project; the stub prints NotImplemented.
const repos: string[] = []
afterEach(() => {
  for (const r of repos.splice(0)) rmSync(r, { recursive: true, force: true })
})

// bun's default timeout is 5 s; each RS call starts bash and Python, so allow more.
const t = (name: string, fn: () => void) => test(name, fn, 60_000)

type Row = { id: string; kind?: string; target?: string; reqs?: string; est?: string; status?: string }

function sh(cwd: string, cmd: string[]) {
  const p = Bun.spawnSync(cmd, { cwd, stdout: 'pipe', stderr: 'pipe', env: { ...process.env } })
  return { code: p.exitCode ?? -1, out: p.stdout.toString(), err: p.stderr.toString() }
}

function parse(out: string): any {
  const line = out.trim().split('\n').filter(Boolean).pop() ?? ''
  try {
    return JSON.parse(line)
  } catch {
    return null
  }
}

function rs(repo: string, ...args: string[]) {
  const r = sh(repo, ['bash', RS_SH, ...args])
  const json = parse(r.out)
  // A Python traceback lands on stderr; show it when an error left no JSON behind.
  if (r.code === 2 && json === null && r.err) console.error(r.err)
  return { ...r, json }
}

function put(repo: string, rel: string, content: string) {
  mkdirSync(dirname(join(repo, rel)), { recursive: true })
  writeFileSync(join(repo, rel), content)
}

function copy(repo: string, from: string, to: string) {
  mkdirSync(dirname(join(repo, to)), { recursive: true })
  cpSync(join(FIX, from), join(repo, to))
}

function plan(rows: Row[]) {
  const head = '| id | checkpoint | kind | target | reqs | est | status | base |\n'
    + '| -- | ---------- | ---- | ------ | ---- | --- | ------ | ---- |\n'
  const body = rows
    .map(r => `| ${r.id} | greeting | ${r.kind ?? 'feature'} | ${r.target ?? '-'} | ${r.reqs ?? '-'} | ${r.est ?? '-'} | ${r.status ?? 'todo'} | |`)
    .join('\n')
  return `# demo\nslug: demo · created: 2026-10-04\n\n${head}${body}\n`
}

function makeRepo(opts: { rows?: Row[]; config?: (c: any) => void } = {}) {
  const repo = mkdtempSync(join(tmpdir(), 'rs-'))
  repos.push(repo)
  sh(repo, ['git', 'init', '-q'])
  copy(repo, 'project/run.sh', 'run.sh')
  copy(repo, 'project/src/greet.sh', 'src/greet.sh')
  copy(repo, 'ratchet/architecture.md', 'docs/architecture.md')
  const cfg = JSON.parse(readFileSync(join(FIX, 'ratchet/config.v2.json'), 'utf8'))
  opts.config?.(cfg)
  put(repo, '.claude/ratchet/config.json', JSON.stringify(cfg, null, 2))
  put(repo, '.claude/ratchet/plans/demo.md', plan(opts.rows ?? [{ id: 'cp1', reqs: 'FR-001,FR-002', est: '20' }]))
  put(repo, '.claude/ratchet/.gitignore', 'evidence/\n')
  return repo
}

const snapBase = (repo: string) => rs(repo, 'snap', 'demo/cp1/base')
const addSpec = (repo: string, ...files: string[]) => files.forEach(f => copy(repo, `spec/${f}`, `tests/${f}`))
const implement = (repo: string) => copy(repo, 'impl/greet.sh', 'src/greet.sh')
const gate = (repo: string, g: string, ...rest: string[]) => rs(repo, 'gate', g, 'demo', 'cp1', '--nonce', 'n1', ...rest)

function review(repo: string, role: 'arch' | 'break', round: number, findings: unknown[], extra: object = {}) {
  put(repo, `${EV}/3-${role}-r${round}.json`, JSON.stringify({ role, round, verdict: findings.length ? 'CHANGES' : 'APPROVE', findings, ...extra }))
}

const readLive = (repo: string) => JSON.parse(readFileSync(join(repo, '.claude/ratchet/live.json'), 'utf8'))
const liveRoles = (repo: string) => readLive(repo).roles.map((r: any) => r.role)

// A repo whose spec is pinned and red, ready for the later gates.
function pinnedRepo(config?: (c: any) => void) {
  const repo = makeRepo({ config })
  snapBase(repo)
  addSpec(repo, 'fr001.sh', 'fr002.sh')
  expect(gate(repo, 'b0').code).toBe(0)
  return repo
}

t('normalizes a version 1 config and a version 1 plan table', () => {
  const repo = makeRepo()
  copy(repo, 'ratchet/config.v1.json', '.claude/ratchet/config.json')
  copy(repo, 'ratchet/plan.v1.md', '.claude/ratchet/plans/ios-settings-themes.md')

  const cfg = JSON.parse(rs(repo, 'config').out)
  expect(cfg.version).toBe(2)
  expect(cfg.caps).toEqual({ b1: 3, b2: 3, b3: 3 })
  expect(cfg.size.prodLines).toBe(800)
  expect(cfg.behavior.extra).toBeUndefined()
  expect(cfg.behavior.one).toBe('mobile/scripts/test-files.sh {files}')
  expect(cfg.checks.map((c: any) => c.id)).toEqual(['extra-1', 'extra-2', 'extra-3', 'extra-4'])
  expect(cfg.checks[2]).toMatchObject({ kind: 'command', run: 'bun run check', gate: ['b1', 'verify'] })
  expect(cfg.architecture).toBe('.claude/ratchet/architecture.md')

  const s = rs(repo, 'state', 'ios-settings-themes').json
  expect(s).toMatchObject({ ok: true, cp: 'cp10', status: 'red', stage: 'B1', kind: 'feature', target: 'home', visual: true })
  expect(s.reqs).toEqual([])
  expect(s.est).toBeNull()
  expect(s.caps).toEqual({ b1: 3, b2: 3, b3: 3 })
  expect(s.refs.base).toBeNull() // a v1 row holds a short SHA that this repo does not have
  expect(rs(repo, 'state', 'ios-settings-themes', 'cp11').json.kind).toBe('refactor')
})

t('derives the stage from the row status when STATE does not exist', () => {
  const repo = makeRepo({
    rows: [
      { id: 'cp1', status: 'approved' }, { id: 'cp2', status: 'red' },
      { id: 'cp3', status: 'todo' }, { id: 'cp4', status: 'green', reqs: 'FR-001, FR-004' },
    ],
  })
  expect(rs(repo, 'state', 'demo').json).toMatchObject({ cp: 'cp2', stage: 'B1', epoch: 1 })
  expect(rs(repo, 'state', 'demo', 'cp3').json.stage).toBe('B0')
  const green = rs(repo, 'state', 'demo', 'cp4').json
  expect(green.stage).toBe('B4')
  expect(green.reqs).toEqual(['FR-001', 'FR-004'])
  expect(rs(repo, 'state', 'demo', 'cp1').json.stage).toBe('done')
  expect(existsSync(join(repo, `${EV}/state.json`))).toBe(false)

  const missing = rs(repo, 'state', 'demo', 'cp9')
  expect(missing.code).toBe(2)
  expect(missing.json).toMatchObject({ ok: false, verdict: 'error' })
  expect(missing.json.harnessError).toContain('cp9')
})

t('b0 tells a compile error from an assertion or a stub, and fails on a missing trace', () => {
  const broken = makeRepo()
  snapBase(broken)
  addSpec(broken, 'fr001.sh', 'fr002.sh', 'fr003-compile.sh')
  const a = gate(broken, 'b0')
  expect(a.code).toBe(1)
  expect(a.json.verdict).toBe('fail')
  expect(a.json.red.compile).toBe(1)
  expect(a.json.red.assert + a.json.red.stub).toBe(2)
  expect(a.json.trace.missing).toEqual([])

  const partial = makeRepo()
  snapBase(partial)
  addSpec(partial, 'fr001.sh')
  const b = gate(partial, 'b0')
  expect(b.code).toBe(1)
  expect(b.json.red.compile).toBe(0)
  expect(b.json.trace.missing).toEqual(['FR-002'])
  expect(b.json.summary).toContain('FR-002')
  // A failed spec gate pins nothing and leaves the stage alone.
  expect(existsSync(join(partial, `${EV}/spec.lock`))).toBe(false)
  expect(rs(partial, 'state', 'demo', 'cp1').json).toMatchObject({ stage: 'B0', rounds: { b0: 1 } })
})

t('b0 pins the tests, snapshots red, moves to B1, and updates LIVE and METRICS', () => {
  const repo = makeRepo()
  snapBase(repo)
  expect(rs(repo, 'live', 'start', 'demo', 'cp1').code).toBe(0)
  addSpec(repo, 'fr001.sh', 'fr002.sh')
  put(repo, 'src/greet.sh', 'echo NotImplemented\n# stub: FR-001 and FR-002 land here\n')
  put(repo, `${EV}/0-spec.json`, JSON.stringify({
    tests: ['tests/fr001.sh', 'tests/fr002.sh'], stubs: ['src/greet.sh'],
    cases: [{ name: 'FR-001 greets the user by name', req: 'FR-001', kind: 'test' },
      { name: 'FR-002 greets the world when no name is given', req: 'FR-002', kind: 'test' }],
  }))

  const r = gate(repo, 'b0')
  expect(r.code).toBe(0)
  expect(r.json).toMatchObject({ ok: true, cmd: 'gate b0', nonce: 'n1', verdict: 'pass', cases: 2, stage: 'B1', round: 1 })
  expect(r.json.red.assert + r.json.red.stub).toBe(2)
  expect([...r.json.tests].sort()).toEqual(['tests/fr001.sh', 'tests/fr002.sh'])
  expect(r.json.stubs).toEqual(['src/greet.sh'])
  expect(r.json.budget).toEqual({ cases: 2, limit: 6, over: false })

  const s = rs(repo, 'state', 'demo', 'cp1').json
  expect(s).toMatchObject({ stage: 'B1', rounds: { b0: 1, b1: 0, b2: 0, b3: 0 }, pins: { intact: 2, changed: 0 } })
  expect(s.refs.red).toMatch(SHA)
  expect(readFileSync(join(repo, `${EV}/spec.lock`), 'utf8')).toContain('tests/fr001.sh')

  const live = JSON.parse(readFileSync(join(repo, '.claude/ratchet/live.json'), 'utf8'))
  expect(live).toMatchObject({ active: true, slug: 'demo', cp: 'cp1', gate: 'B0', round: 1 })
  const lines = readFileSync(join(repo, '.claude/ratchet/metrics.jsonl'), 'utf8').trim().split('\n')
  expect(lines.length).toBe(1)
  expect(JSON.parse(lines[0])).toMatchObject({ slug: 'demo', cp: 'cp1', gate: 'b0', round: 1, verdict: 'pass' })
})

t('b1 puts a changed pin back and fails the round', () => {
  const repo = pinnedRepo()
  const original = readFileSync(join(repo, 'tests/fr001.sh'), 'utf8')
  writeFileSync(join(repo, 'tests/fr001.sh'), 'exit 0\n')
  const r = gate(repo, 'b1')
  expect(r.code).toBe(1)
  expect(r.json.verdict).toBe('fail')
  expect(r.json.pinsChanged).toEqual(['tests/fr001.sh'])
  expect(readFileSync(join(repo, 'tests/fr001.sh'), 'utf8')).toBe(original)
  expect(readFileSync(join(repo, `${EV}/1-brief-r2.md`), 'utf8')).toContain('tests/fr001.sh')
  expect(rs(repo, 'state', 'demo', 'cp1').json.pins).toEqual({ intact: 2, changed: 0 })
})

t('b1 runs a scoped check only when a changed file matches its globs', () => {
  const repo = pinnedRepo(c => {
    c.checks = [
      { id: 'sh-only', kind: 'command', run: 'echo ran-sh', when: ['**/*.sh'], gate: ['b1'] },
      { id: 'md-only', kind: 'command', run: 'echo ran-md', when: ['**/*.md'], gate: ['b1'] },
      { id: 'always', kind: 'command', run: 'echo ran', gate: ['b1', 'verify'] },
      { id: 'verify-only', kind: 'command', run: 'echo nope', gate: ['verify'] },
    ]
  })
  implement(repo)
  const r = gate(repo, 'b1')
  expect(r.code).toBe(0)
  expect(r.json.checks.map((c: any) => c.id)).toEqual(['pinned', 'sh-only', 'always', 'behavior'])
  expect(r.json).toMatchObject({ verdict: 'pass', failing: [], stage: 'B3' })
  expect(r.json.size.est).toBe(20)
  expect(readFileSync(join(repo, r.json.evidence), 'utf8')).toContain('ran-sh')
  expect(rs(repo, 'state', 'demo', 'cp1').json.rounds.b1).toBe(1)
})

t('exec stops a command and its children at the timeout, and exits 124', () => {
  const repo = makeRepo()
  const started = Date.now()
  const slow = rs(repo, 'exec', '--timeout', '1', '--', 'sh', '-c', '(sleep 2; echo late > late.txt) & wait')
  expect(slow.code).toBe(124)
  expect(Date.now() - started).toBeLessThan(15_000)
  Bun.sleepSync(2500) // a child that outlived the kill would write late.txt by now
  expect(existsSync(join(repo, 'late.txt'))).toBe(false)
  expect(rs(repo, 'exec', '--timeout', '5', '--', 'sh', '-c', 'exit 3').code).toBe(3)
})

t('size --prod counts production lines apart from tests, lockfiles and generated files', () => {
  const repo = makeRepo()
  const base = rs(repo, 'snap').out.trim()
  put(repo, 'src/new.sh', 'a\nb\nc\n')
  put(repo, 'tests/new.sh', 'x\ny\n')
  put(repo, 'package-lock.json', '{}\n'.repeat(10))
  put(repo, 'dist/bundle.js', 'z\n'.repeat(7))
  const r = rs(repo, 'size', '--prod', base)
  expect(r.code).toBe(0)
  expect(r.json).toMatchObject({ verdict: 'pass', prod: 3, tests: 2 })
})

function proofRepo() {
  const repo = makeRepo()
  put(repo, `${EV}/proofs/p1.sh`, 'echo "boom: expected 3, received 2"\nexit 1\n')
  put(repo, `${EV}/proofs/p2.sh`, 'echo stray > stray.txt\necho "x" >> src/greet.sh\necho boom\nexit 1\n')
  review(repo, 'break', 1, [
    { id: 'cp1-B1-1', severity: 'high', issue: 'wrong count', proof: { cmd: `sh ${EV}/proofs/p1.sh`, pattern: 'expected 3, received 2' } },
    { id: 'cp1-B1-2', severity: 'high', issue: 'no pattern', proof: { cmd: `sh ${EV}/proofs/p1.sh` } },
    { id: 'cp1-B1-3', severity: 'high', issue: 'touches the tree', proof: { cmd: `sh ${EV}/proofs/p2.sh`, pattern: 'boom' } },
  ])
  return repo
}

t('prove: a failing command whose output matches the pattern reproduces', () => {
  const repo = proofRepo()
  const r = rs(repo, 'prove', 'demo', 'cp1', 'cp1-B1-1')
  expect(r.code).toBe(0)
  expect(r.json).toMatchObject({ verdict: 'pass', id: 'cp1-B1-1', result: 'reproduced', exit: 1 })
  expect(readFileSync(join(repo, r.json.evidence), 'utf8')).toContain('boom')
})

t('prove: a proof without a pattern is unproven', () => {
  const repo = proofRepo()
  const r = rs(repo, 'prove', 'demo', 'cp1', 'cp1-B1-2')
  expect(r.code).toBe(1)
  expect(r.json).toMatchObject({ verdict: 'fail', result: 'unproven', exit: 1 })
})

t('prove: a proof that changes the tree is restored and marked invalid', () => {
  const repo = proofRepo()
  const before = readFileSync(join(repo, 'src/greet.sh'), 'utf8')
  const r = rs(repo, 'prove', 'demo', 'cp1', 'cp1-B1-3')
  expect(r.code).toBe(1)
  expect(r.json).toMatchObject({ result: 'invalid', restored: true })
  expect([...r.json.changed].sort()).toEqual(['src/greet.sh', 'stray.txt'])
  expect(existsSync(join(repo, 'stray.txt'))).toBe(false)
  expect(readFileSync(join(repo, 'src/greet.sh'), 'utf8')).toBe(before)
})

t('b3 blocks an architecture finding only when its rule exists', () => {
  const repo = makeRepo()
  review(repo, 'arch', 1, [
    { id: 'cp1-A1-1', severity: 'high', file: 'src/greet.sh', issue: 'a comment restates the code', rule: 'ARCH-COMMENTS' },
    { id: 'cp1-A1-2', severity: 'high', file: 'src/greet.sh', issue: 'cites a rule that is not there', rule: 'ARCH-MADE-UP' },
    { id: 'cp1-A1-3', severity: 'low', file: 'src/greet.sh', issue: 'taste, no rule' },
  ])
  review(repo, 'break', 1, [])
  const r = gate(repo, 'b3')
  expect(r.code).toBe(1)
  expect(r.json.blocking).toEqual(['cp1-A1-1'])
  expect(r.json.advisory).toEqual(['cp1-A1-2', 'cp1-A1-3'])
  expect(rs(repo, 'state', 'demo', 'cp1').json.open).toEqual({ blocking: ['cp1-A1-1'], advisory: ['cp1-A1-2', 'cp1-A1-3'] })
  const triage = JSON.parse(readFileSync(join(repo, `${EV}/3-triage-r1.json`), 'utf8'))
  expect(triage.findings.map((f: any) => [f.id, f.ruleExists])).toEqual([['cp1-A1-1', true], ['cp1-A1-2', false], ['cp1-A1-3', false]])
})

t('b3 does not block on a learnings rule that is retired', () => {
  const repo = makeRepo()
  put(repo, '.claude/ratchet/learnings.md', '# Learnings\n\n'
    + '### L-001\n- scope: src/**\n- rule: Keep the greeting short.\n- helpful: 0 · harmful: 0 · status: active\n\n'
    + '### L-002\n- scope: src/**\n- rule: An old rule.\n- helpful: 0 · harmful: 3 · status: retired\n')
  review(repo, 'arch', 1, [
    { id: 'cp1-A1-1', severity: 'medium', file: 'src/greet.sh', issue: 'long greeting', rule: 'L-001' },
    { id: 'cp1-A1-2', severity: 'medium', file: 'src/greet.sh', issue: 'breaks the old rule', rule: 'L-002' },
  ])
  review(repo, 'break', 1, [])
  const r = gate(repo, 'b3')
  expect(r.json.blocking).toEqual(['cp1-A1-1'])
  expect(r.json.advisory).toEqual(['cp1-A1-2'])
})

t('learnings keeps the old rules without IDs after a dream adds an entry', () => {
  const repo = makeRepo()
  put(repo, '.claude/ratchet/learnings.md', '# Learnings\n\n- Verify the insets on a device.\n\n'
    + '### L-001\n- scope: server/**\n- rule: Log the request ID.\n- helpful: 0 · harmful: 0 · status: active\n')
  const out = sh(repo, ['bash', RS_SH, 'learnings', '--scope', 'mobile/a.kt']).out
  expect(out).toContain('Verify the insets on a device.')
  expect(out).not.toContain('L-001')
})

t('b3 reads version 1 verdicts as advisory, under new IDs', () => {
  const repo = makeRepo()
  copy(repo, 'verdicts/v1-arch.json', `${EV}/3-review-arch-r1.json`)
  copy(repo, 'verdicts/v1-break.json', `${EV}/3-review-break-r1.json`)
  const r = gate(repo, 'b3')
  expect(r.code).toBe(0)
  expect(r.json).toMatchObject({
    verdict: 'pass', blocking: [], stage: 'B4',
    advisory: ['cp1-A1-901', 'cp1-B1-901', 'cp1-B1-902'], unproven: ['cp1-B1-901', 'cp1-B1-902'],
  })
  const triage = JSON.parse(readFileSync(join(repo, `${EV}/3-triage-r1.json`), 'utf8'))
  expect(triage.findings.map((f: any) => f.rawId)).toEqual(['A1', 'B1', 'B2'])
  expect(rs(repo, 'state', 'demo', 'cp1').json.refs.gated).toMatch(SHA)
})

t('b3 in round 2 proves the open findings again and marks a fixed one addressed', () => {
  const repo = makeRepo()
  put(repo, `${EV}/proofs/p1.sh`, 'if grep -q NotImplemented src/greet.sh; then echo "still broken: NotImplemented"; exit 1; fi\n')
  snapBase(repo)
  const prep1 = gate(repo, 'b3-prep')
  expect(prep1.json).toMatchObject({ verdict: 'pass', structural: true, delta: null, checkOutputs: [] })
  expect(prep1.json.evidence).toBe(prep1.json.patch)
  review(repo, 'arch', 1, [])
  review(repo, 'break', 1, [
    { id: 'cp1-B1-1', severity: 'high', issue: 'the stub is still there', proof: { cmd: `sh ${EV}/proofs/p1.sh`, pattern: 'still broken' } },
  ])
  const r1 = gate(repo, 'b3')
  expect(r1.code).toBe(1)
  expect(r1.json.blocking).toEqual(['cp1-B1-1'])
  expect(rs(repo, 'state', 'demo', 'cp1').json.open.blocking).toEqual(['cp1-B1-1'])

  implement(repo)
  const prep2 = gate(repo, 'b3-prep')
  expect(prep2.json).toMatchObject({ round: 2, structural: false })
  expect(readFileSync(join(repo, prep2.json.delta), 'utf8')).toContain('Hello')
  // The delta changes no file set and touches no archPaths, so only the break reviewer runs.
  review(repo, 'break', 2, [], { addressed: [{ id: 'cp1-B1-1', status: 'ADDRESSED' }] })
  const r2 = gate(repo, 'b3')
  expect(r2.code).toBe(0)
  expect(r2.json).toMatchObject({ verdict: 'pass', round: 2, blocking: [], addressed: ['cp1-B1-1'], notAddressed: [], stage: 'B4' })
  expect(rs(repo, 'state', 'demo', 'cp1').json).toMatchObject({ rounds: { b3: 2 }, open: { blocking: [] } })
})

t('stdout is one JSON object of 1 KB or less, with the sha256 of its evidence file', () => {
  const repo = pinnedRepo(c => {
    c.checks = Array.from({ length: 40 }, (_, i) => ({
      id: `check-with-a-long-name-${i}`, kind: 'command', run: `echo ${'x'.repeat(100)}`, gate: ['b1'],
    }))
  })
  implement(repo)
  const r = gate(repo, 'b1')
  const out = r.out.trimEnd()
  expect(out.includes('\n')).toBe(false)
  expect(Buffer.byteLength(out)).toBeLessThanOrEqual(1024)
  expect(r.json.verdict).toBe('pass')
  expect(r.json.sha256).toBe(createHash('sha256').update(readFileSync(join(repo, r.json.evidence))).digest('hex'))
  expect(r.json.checks.length).toBeLessThan(41)
  expect(r.json.checksMore + r.json.checks.length).toBe(42) // 40 checks, pinned and behavior
})

t('retire unpins a test file and records the reason', () => {
  const repo = pinnedRepo()
  const r = rs(repo, 'retire', 'demo', 'cp1', 'tests/fr001.sh', '--reason', 'FR-001 moved to cp2')
  expect(r.code).toBe(0)
  expect(rs(repo, 'state', 'demo', 'cp1').json.pins).toEqual({ intact: 1, changed: 0 })
  expect(readFileSync(join(repo, `${EV}/spec.lock`), 'utf8')).not.toContain('tests/fr001.sh')
  expect(readFileSync(join(repo, `${EV}/0-amendments.md`), 'utf8')).toContain('tests/fr001.sh: FR-001 moved to cp2')

  implement(repo)
  writeFileSync(join(repo, 'tests/fr001.sh'), '# FR-001 rewritten\nexit 0\n')
  expect(gate(repo, 'b1').json).toMatchObject({ verdict: 'pass', pinsChanged: [] })

  expect(rs(repo, 'retire', 'demo', 'cp1', 'tests/nope.sh', '--reason', 'x').code).toBe(2)
  expect(rs(repo, 'retire', 'demo', 'cp1', 'tests/fr002.sh').code).toBe(2)
})

t('lock --from reads the paths from a file and keeps names with spaces whole', () => {
  const repo = makeRepo()
  put(repo, 'a file.txt', 'one\n')
  put(repo, 'b.txt', 'two\n')
  put(repo, 'list.txt', 'a file.txt\nb.txt\n')
  const locked = sh(repo, ['bash', RS_SH, 'lock', 'pins', '--from', 'list.txt'])
  expect(locked.code).toBe(0)
  expect(locked.out).toContain('locked 2 file(s)')
  expect(sh(repo, ['bash', RS_SH, 'check', 'pins']).code).toBe(0)
  writeFileSync(join(repo, 'a file.txt'), 'changed\n')
  const bad = sh(repo, ['bash', RS_SH, 'check', 'pins'])
  expect(bad.code).toBe(1)
  expect(bad.out).toContain('CHANGED  a file.txt')
  expect(sh(repo, ['bash', RS_SH, 'lock', 'pins', '--from', 'missing.txt']).code).toBe(2)
})

t('red-check lets compile win over assert, and failureKinds replace a family', () => {
  const repo = makeRepo()
  put(repo, 'both.txt', 'AssertionError: expected 1\nerror TS2307: Cannot find module "./x"\n')
  expect(rs(repo, 'red-check', 'both.txt')).toMatchObject({ code: 1, json: { kind: 'compile' } })
  put(repo, 'assert.txt', 'AssertionError: expected 1\n')
  expect(rs(repo, 'red-check', 'assert.txt')).toMatchObject({ code: 0, json: { kind: 'assert' } })
  put(repo, 'stub.txt', 'NotImplementedError: todo\n')
  expect(rs(repo, 'red-check', 'stub.txt').json.kind).toBe('stub')
  put(repo, 'runner.txt', 'the runner died\n')
  expect(rs(repo, 'red-check', 'runner.txt').json.kind).toBe('runner')

  const cfg = JSON.parse(readFileSync(join(repo, '.claude/ratchet/config.json'), 'utf8'))
  cfg.behavior.failureKinds = { assert: ['BOOM'] }
  writeFileSync(join(repo, '.claude/ratchet/config.json'), JSON.stringify(cfg))
  put(repo, 'boom.txt', 'BOOM happened\n')
  expect(rs(repo, 'red-check', 'boom.txt').json.kind).toBe('assert')
  expect(rs(repo, 'red-check', 'assert.txt').json.kind).toBe('runner')
})

t('b0-prep takes the base only once, records the baseline, pins the state files and starts LIVE', () => {
  const repo = makeRepo({ config: c => { c.checks = [{ id: 'legacy', kind: 'command', run: 'exit 3', gate: ['b1'] }] } })
  const first = gate(repo, 'b0-prep')
  expect(first.json.verdict).toBe('pass')
  expect(first.json.baselineFailing).toContain('legacy')
  put(repo, 'src/later.sh', 'echo later\n')
  expect(gate(repo, 'b0-prep').json.base).toBe(first.json.base)
  expect(existsSync(join(repo, '.claude/ratchet/evidence/demo/_state/spec.lock'))).toBe(true)
  const live = JSON.parse(readFileSync(join(repo, '.claude/ratchet/live.json'), 'utf8'))
  expect(live).toMatchObject({ active: true, slug: 'demo', cp: 'cp1', gate: 'B0' })
})

t('b1 passes over a check that failed before the checkpoint, and names it', () => {
  const repo = makeRepo({ config: c => { c.checks = [{ id: 'legacy', kind: 'command', run: 'exit 3', gate: ['b1'] }] } })
  expect(gate(repo, 'b0-prep').code).toBe(0)
  addSpec(repo, 'fr001.sh', 'fr002.sh')
  expect(gate(repo, 'b0').code).toBe(0)
  implement(repo)
  expect(gate(repo, 'b1').json).toMatchObject({ verdict: 'pass', failing: [], baselineFailing: ['legacy'] })

  // The report names the check and still ends with the report path, inside its 10 lines.
  const report = sh(repo, ['bash', RS_SH, 'report', 'demo', 'cp1'])
  const lines = report.out.trim().split('\n')
  expect(report.code).toBe(0)
  expect(lines.length).toBeLessThanOrEqual(10)
  expect(lines.find(l => l.startsWith('Advisory findings'))).toContain('failed before the row: legacy')
  expect(lines[lines.length - 1]).toStartWith('Report:')
  expect(readFileSync(join(repo, `${EV}/4-report.md`), 'utf8')).toContain('- legacy')
})

t('b1 stops with an error when a state file changed, and leaves the change for the human', () => {
  const repo = makeRepo()
  expect(gate(repo, 'b0-prep').code).toBe(0)
  addSpec(repo, 'fr001.sh', 'fr002.sh')
  expect(gate(repo, 'b0').code).toBe(0)
  implement(repo)
  const path = join(repo, '.claude/ratchet/config.json')
  const edited = readFileSync(path, 'utf8').replace('"perCheckpoint": 20', '"perCheckpoint": 99')
  writeFileSync(path, edited)
  const b1 = gate(repo, 'b1')
  expect(b1.code).toBe(2)
  expect(b1.json.summary).toContain('state files changed')
  expect(readFileSync(path, 'utf8')).toBe(edited)
})

t('decide --reopen b1 sets the stage and puts the decision on top of the next brief', () => {
  const repo = pinnedRepo()
  const d = rs(repo, 'decide', 'demo', 'cp1', 'Use the cached list.', '--reopen', 'b1')
  expect(d.json).toMatchObject({ verdict: 'pass', stage: 'B1', brief: `${EV}/1-brief-r1.md` })
  expect(readFileSync(join(repo, d.json.brief), 'utf8')).toContain('Use the cached list.')
  expect(rs(repo, 'state', 'demo', 'cp1').json).toMatchObject({ stage: 'B1', epoch: d.json.epoch })

  // A failed round leaves the brief for the next round. The decision must not replace it.
  writeFileSync(join(repo, 'tests/fr001.sh'), 'exit 0\n')
  expect(gate(repo, 'b1').code).toBe(1)
  const again = rs(repo, 'decide', 'demo', 'cp1', 'Keep the old format.', '--reopen', 'b1')
  expect(again.json.brief).toBe(`${EV}/1-brief-r2.md`)
  const brief = readFileSync(join(repo, again.json.brief), 'utf8')
  expect(brief.startsWith('## Decision from the human\nKeep the old format.\n')).toBe(true)
  expect(brief).toContain('tests/fr001.sh')
})

t('row changes the status and adds a note, and the table still parses', () => {
  const repo = makeRepo()
  const r = rs(repo, 'row', 'demo', 'cp1', 'blocked', '--note', 'blocked: the API has no paging')
  expect(r.json).toMatchObject({ verdict: 'pass', changes: { status: 'blocked' } })
  expect(readFileSync(join(repo, '.claude/ratchet/plans/demo.md'), 'utf8')).toContain('- cp1 · blocked: the API has no paging')
  expect(rs(repo, 'state', 'demo', 'cp1').json.status).toBe('blocked')
})

t('learnings --scope keeps the active entries whose scope matches the paths', () => {
  const repo = makeRepo()
  const entry = (id: string, scope: string, rule: string, status: string) =>
    `### ${id}\n- scope: ${scope}\n- rule: ${rule}\n- helpful: 0 · harmful: 0 · status: ${status}\n\n`
  put(repo, '.claude/ratchet/learnings.md', '# Learnings\n\n'
    + entry('L-001', 'mobile/**', 'Check the keyboard.', 'active')
    + entry('L-002', 'server/**', 'Log the request ID.', 'active')
    + entry('L-003', 'mobile/**', 'An old rule.', 'retired'))
  const out = sh(repo, ['bash', RS_SH, 'learnings', '--scope', 'mobile/app/Form.kt']).out
  expect(out).toContain('L-001')
  expect(out).not.toContain('L-002')
  expect(out).not.toContain('L-003')

  const all = sh(repo, ['bash', RS_SH, 'learnings', '--all']).out
  expect(all).toContain('L-001')
  expect(all).toContain('L-002')
  expect(all).not.toContain('L-003')
})

t('gate --detach returns at once, and wait gives the gate result under its own nonce, or pending', () => {
  const repo = pinnedRepo(c => { c.checks = [{ id: 'slow', kind: 'command', run: 'sleep 5', gate: ['b1'] }] })
  implement(repo)
  const started = Date.now()
  const d = gate(repo, 'b1', '--round', '1', '--detach')
  // A stream that stays open to the job would hold this call until the gate ends, 5 s or more.
  expect(Date.now() - started).toBeLessThan(4000)
  expect(d.code).toBe(0)
  expect(d.json).toMatchObject({ ok: true, cmd: 'gate b1', nonce: 'n1', verdict: 'pending', summary: 'started', job: 'b1-r1-n1' })

  const wait = (nonce: string, seconds: string, job = 'b1-r1-n1') =>
    rs(repo, 'wait', 'demo', 'cp1', job, '--nonce', nonce, '--timeout', seconds)
  const early = wait('w1', '1')
  expect(early.code).toBe(0)
  expect(early.json).toMatchObject({ ok: true, verdict: 'pending', nonce: 'w1', job: 'b1-r1-n1', summary: 'still running after 1 s' })

  const done = wait('w2', '60')
  expect(done.code).toBe(0)
  expect(done.json).toMatchObject({ cmd: 'gate b1', verdict: 'pass', nonce: 'w2', job: 'b1-r1-n1', round: 1 })
  expect(done.json.checks.map((c: any) => c.id)).toEqual(['pinned', 'slow', 'behavior'])

  // A job that died without output is an error at once, not a wait for the whole timeout.
  put(repo, `${EV}/.jobs/ghost.json`, '')
  put(repo, `${EV}/.jobs/ghost.pid`, `${Bun.spawnSync(['true']).pid}\n`)
  const ghost = wait('w3', '30', 'ghost')
  expect(ghost.code).toBe(2)
  expect(ghost.json).toMatchObject({ verdict: 'error', nonce: 'w3', summary: 'job ended without output' })
  expect(wait('w4', '30', 'nope').code).toBe(2)
  // Output of another command in the job file is no result.
  put(repo, `${EV}/.jobs/noise.json`, '{"status":"ok"}\n')
  put(repo, `${EV}/.jobs/noise.pid`, `${Bun.spawnSync(['true']).pid}\n`)
  expect(wait('w5', '30', 'noise').json.summary).toBe('job ended without output')
})

t('a detached b2-capture keeps the output of ready and teardown out of its result', () => {
  const repo = makeRepo({
    rows: [{ id: 'cp1', target: 'profile' }],
    config: c => {
      c.visual = {
        mode: 'browser', setup: 'sleep 60', ready: `printf '{"status":"ok"}'`, teardown: `printf '{"bye":true}'`,
        capture: 'printf x > {out}', viewports: [375], reference: { kind: 'none' },
      }
    },
  })
  const d = gate(repo, 'b2-capture', '--round', '1', '--detach')
  expect(d.json.verdict).toBe('pending')
  const w = rs(repo, 'wait', 'demo', 'cp1', d.json.job, '--nonce', 'w1', '--timeout', '60')
  // No reference image, so the images differ and a visual judgment is due.
  expect(w.json).toMatchObject({ cmd: 'gate b2-capture', verdict: 'fail', nonce: 'w1' })
  expect(readFileSync(join(repo, `${EV}/2-ready-r1.log`), 'utf8')).toBe('{"status":"ok"}')
  expect(readFileSync(join(repo, `${EV}/2-teardown-r1.log`), 'utf8')).toBe('{"bye":true}')
})

t('b1 runs the pinned tests as a check of their own, and the baseline never excuses it', () => {
  const repo = makeRepo()
  expect(gate(repo, 'b0-prep').code).toBe(0) // no tests exist yet, so behavior.all fails in the baseline
  addSpec(repo, 'fr001.sh', 'fr002.sh')
  expect(gate(repo, 'b0').code).toBe(0)
  const failed = gate(repo, 'b1')
  expect(failed.code).toBe(1)
  expect(failed.json).toMatchObject({ verdict: 'fail', failing: ['pinned'], baselineFailing: ['behavior'] })
  expect(failed.json.checks[0].id).toBe('pinned')
  expect(readFileSync(join(repo, `${EV}/1-brief-r2.md`), 'utf8')).toContain('## pinned')
  expect(liveRoles(repo)).toEqual(['implement'])
  implement(repo)
  expect(gate(repo, 'b1').json).toMatchObject({ verdict: 'pass', failing: [], baselineFailing: [] })
})

t('b0 locks an earlier test that the spec amended, so b1 does not put the old one back', () => {
  const repo = makeRepo({
    rows: [{ id: 'cp1', reqs: 'FR-001,FR-002', est: '20' }, { id: 'cp2', reqs: 'FR-003', est: '20' }],
  })
  expect(gate(repo, 'b0-prep').code).toBe(0)
  addSpec(repo, 'fr001.sh', 'fr002.sh')
  expect(gate(repo, 'b0').code).toBe(0)
  implement(repo)
  expect(gate(repo, 'b1').code).toBe(0)

  const EV2 = '.claude/ratchet/evidence/demo/cp2'
  const two = (g: string, ...rest: string[]) => rs(repo, 'gate', g, 'demo', 'cp2', '--nonce', 'n2', ...rest)
  expect(two('b0-prep').code).toBe(0)
  addSpec(repo, 'fr003.sh')
  const amended = readFileSync(join(repo, 'tests/fr001.sh'), 'utf8') + '# FR-001 still holds with the shout option\n'
  writeFileSync(join(repo, 'tests/fr001.sh'), amended)
  put(repo, `${EV2}/0-spec.json`, JSON.stringify({
    tests: ['tests/fr001.sh', 'tests/fr003.sh'], stubs: [],
    amendments: [{ path: 'tests/fr001.sh', reason: 'the greeting can shout now' }],
    cases: [{ name: 'FR-003 shouts the greeting when asked', req: 'FR-003', kind: 'test' }],
  }))
  const b0 = two('b0')
  expect(b0.json).toMatchObject({ verdict: 'pass', amended: ['tests/fr001.sh'] })
  expect(readFileSync(join(repo, `${EV2}/0-amendments.md`), 'utf8')).toContain('- tests/fr001.sh: the greeting can shout now')
  // The older lock holds the amended file now.
  expect(sh(repo, ['bash', RS_SH, 'check', '.claude/ratchet/evidence/demo/cp1']).code).toBe(0)

  copy(repo, 'impl/greet-shout.sh', 'src/greet.sh')
  const b1 = two('b1')
  expect(b1.json).toMatchObject({ verdict: 'pass', pinsChanged: [] })
  expect(readFileSync(join(repo, 'tests/fr001.sh'), 'utf8')).toBe(amended)
})

t('b0-prep runs the baseline before it takes the base, and writes context.md, learnings.md and the base column', () => {
  const repo = makeRepo({
    rows: [{ id: 'cp1', reqs: 'FR-001,FR-002', est: '20' }, { id: 'cp10' }],
    config: c => { c.checks = [{ id: 'artifact', kind: 'command', run: 'echo built > artifact.txt', gate: ['b1'] }] },
  })
  put(repo, 'docs/changes/0001-demo/spec.md', '# Spec\n')
  put(repo, 'docs/changes/0001-demo/design-log.md', '# Design log\n')
  put(repo, '.claude/ratchet/learnings.md', '# Learnings\n\n- Loose rule.\n\n'
    + '### L-001\n- scope: mobile/**\n- rule: Check the keyboard.\n- helpful: 0 · harmful: 0 · status: active\n')
  rs(repo, 'row', 'demo', 'cp1', '--note', 'scope: greet only')
  rs(repo, 'row', 'demo', 'cp1', '--note', 'waive(cp1): regression home — the header moved on purpose')
  rs(repo, 'row', 'demo', 'cp10', '--note', 'scope: not this row')

  const prep = gate(repo, 'b0-prep')
  expect(prep.code).toBe(0)
  // The file that the baseline wrote is in the base: nothing differs from it yet.
  expect(sh(repo, ['bash', RS_SH, 'changed', 'refs/ratchet/demo/cp1/base']).code).toBe(0)
  expect(liveRoles(repo)).toEqual(['spec'])

  const context = readFileSync(join(repo, `${EV}/context.md`), 'utf8')
  expect(context).toMatch(/- plan: \/.*\/\.claude\/ratchet\/plans\/demo\.md\n/)
  expect(context).toContain('- reqs: FR-001, FR-002')
  expect(context).toContain('- cp1 · scope: greet only')
  expect(context).toContain('- cp1 · waive(cp1): regression home')
  expect(context).not.toContain('not this row')
  expect(context).toMatch(/- \/.*\/docs\/changes\/0001-demo\/spec\.md\n/)
  expect(context).toMatch(/- \/.*\/docs\/changes\/0001-demo\/design-log\.md\n/)
  expect(context).toMatch(/- architecture: \/.*\/docs\/architecture\.md\n/)
  expect(context).toContain('`sh run.sh {files}`')
  expect(context).toContain('- budget: 3 per requirement, 20 per checkpoint')

  const learnings = readFileSync(join(repo, `${EV}/learnings.md`), 'utf8')
  expect(learnings).toContain('Loose rule.')
  expect(learnings).toContain('L-001')
  const planText = readFileSync(join(repo, '.claude/ratchet/plans/demo.md'), 'utf8')
  expect(planText).toContain(`| todo | ${prep.json.base.slice(0, 12)} |`)

  // b3-prep writes the file again, for the changed files only: L-001 is scoped to mobile/.
  put(repo, 'src/new.sh', 'echo new\n')
  expect(gate(repo, 'b3-prep').code).toBe(0)
  const scoped = readFileSync(join(repo, `${EV}/learnings.md`), 'utf8')
  expect(scoped).toContain('Loose rule.')
  expect(scoped).not.toContain('L-001')
  expect(liveRoles(repo)).toEqual(['arch', 'break'])
})

t('b0 pass sets the row red and b3 pass sets it green, and LIVE names the roles that work next', () => {
  const repo = makeRepo()
  const status = () => rs(repo, 'state', 'demo', 'cp1').json.status
  expect(gate(repo, 'b0-prep').code).toBe(0)
  expect(liveRoles(repo)).toEqual(['spec'])
  expect(gate(repo, 'b0').code).toBe(1) // no spec yet
  expect(liveRoles(repo)).toEqual(['spec'])
  expect(status()).toBe('todo')

  addSpec(repo, 'fr001.sh', 'fr002.sh')
  expect(gate(repo, 'b0').code).toBe(0)
  expect(status()).toBe('red')
  expect(liveRoles(repo)).toEqual(['implement'])

  implement(repo)
  expect(gate(repo, 'b1').code).toBe(0)
  expect(gate(repo, 'smoke').code).toBe(0)
  expect(liveRoles(repo)).toEqual(['arch', 'break'])

  review(repo, 'arch', 1, [])
  review(repo, 'break', 1, [])
  expect(gate(repo, 'b3').code).toBe(0)
  expect(status()).toBe('green')
  expect(readLive(repo)).toMatchObject({ active: true, gate: 'B4', roles: [] })
})

t('b2 blocks a regression of an earlier target unless the plan waives it', () => {
  const repo = makeRepo({
    rows: [{ id: 'cp1', target: 'profile' }],
    config: c => { c.visual = { mode: 'render', capture: 'true', viewports: [375], reference: { kind: 'none' } } },
  })
  const captured = (round: number, regressChanged: string[]) => {
    put(repo, `${EV}/2-visual-r${round}.json`, JSON.stringify({ verdict: 'PASS', differences: [] }))
    put(repo, `${EV}/2-capture-r${round}.json`, JSON.stringify({ round, images: [], identical: true, regressChanged }))
  }
  captured(1, ['home', 'settings'])
  const r1 = gate(repo, 'b2')
  expect(r1.code).toBe(1)
  expect(r1.json.blocking).toEqual(['cp1-V1-101', 'cp1-V1-102'])
  const triage = JSON.parse(readFileSync(join(repo, `${EV}/2-triage-r1.json`), 'utf8'))
  expect(triage.differences.map((d: any) => [d.id, d.kind, d.element])).toEqual([
    ['cp1-V1-101', 'regression', 'home'], ['cp1-V1-102', 'regression', 'settings'],
  ])

  rs(repo, 'row', 'demo', 'cp1', '--note', 'waive(cp1): regression home — the header moved on purpose')
  captured(2, ['home', 'settings'])
  expect(gate(repo, 'b2').json).toMatchObject({ verdict: 'fail', blocking: ['cp1-V2-102'], advisory: ['cp1-V2-101'] })

  // A waiver can name a range of rows.
  rs(repo, 'row', 'demo', 'cp1', '--note', 'waive(cp0–cp2): regression settings — the same change')
  captured(3, ['home', 'settings'])
  expect(gate(repo, 'b2').json).toMatchObject({ verdict: 'pass', blocking: [], stage: 'B3' })
})

t('b3 gives a malformed finding ID a new one, finds it by the old one in round 2, and leaves nothing open', () => {
  const repo = makeRepo()
  // A malformed ID that an older run left in STATE: no later round could close it, so the triage drops it.
  put(repo, `${EV}/state.json`, JSON.stringify({ open: { blocking: ['B7'], advisory: [] } }))
  put(repo, `${EV}/proofs/p1.sh`, 'if grep -q NotImplemented src/greet.sh; then echo "still broken"; exit 1; fi\n')
  review(repo, 'arch', 1, [
    { id: 'arch-1', severity: 'high', file: 'src/greet.sh', issue: 'a comment restates the code', rule: 'ARCH-COMMENTS' },
  ])
  review(repo, 'break', 1, [
    { id: 'bug 7', severity: 'high', issue: 'the stub is still there', proof: { cmd: `sh ${EV}/proofs/p1.sh`, pattern: 'still broken' } },
  ])
  const r1 = gate(repo, 'b3')
  expect(r1.code).toBe(1)
  expect(r1.json.blocking).toEqual(['cp1-A1-901', 'cp1-B1-901'])
  const triage = JSON.parse(readFileSync(join(repo, `${EV}/3-triage-r1.json`), 'utf8'))
  expect(triage.findings.map((f: any) => [f.id, f.rawId])).toEqual([['cp1-A1-901', 'arch-1'], ['cp1-B1-901', 'bug 7']])
  expect(rs(repo, 'state', 'demo', 'cp1').json.open.blocking).toEqual(['cp1-A1-901', 'cp1-B1-901'])

  // The reviewers read their own files from round 1, so they name the findings by the old IDs.
  implement(repo)
  review(repo, 'arch', 2, [], { addressed: [{ id: 'arch-1', status: 'ADDRESSED' }] })
  review(repo, 'break', 2, [])
  const r2 = gate(repo, 'b3')
  expect(r2.code).toBe(0)
  expect(r2.json).toMatchObject({ verdict: 'pass', blocking: [], addressed: ['cp1-A1-901', 'cp1-B1-901'] })
  expect(rs(repo, 'state', 'demo', 'cp1').json.open.blocking).toEqual([])
})

t('prove copies the files that a proof changed to a backup before it restores them', () => {
  const repo = proofRepo()
  const before = readFileSync(join(repo, 'src/greet.sh'), 'utf8')
  const r = rs(repo, 'prove', 'demo', 'cp1', 'cp1-B1-3')
  expect(r.json).toMatchObject({ result: 'invalid', restored: true, backup: `${EV}/proofs/cp1-B1-3.backup` })
  const backup = join(repo, r.json.backup)
  expect(readFileSync(join(backup, 'stray.txt'), 'utf8')).toBe('stray\n')
  expect(readFileSync(join(backup, 'src/greet.sh'), 'utf8')).toBe(before + 'x\n')
  expect(existsSync(join(repo, 'stray.txt'))).toBe(false)
  expect(readFileSync(join(repo, 'src/greet.sh'), 'utf8')).toBe(before)
})

t('--root runs the command in that repo from a folder outside any repo', () => {
  const repo = makeRepo()
  const outside = mkdtempSync(join(tmpdir(), 'rs-out-'))
  repos.push(outside)
  const r = sh(outside, ['bash', RS_SH, 'config', '--root', repo])
  expect(r.code).toBe(0)
  expect(JSON.parse(r.out).version).toBe(2)
  const s = sh(outside, ['bash', RS_SH, '--root', repo, 'state', 'demo', 'cp1'])
  expect(parse(s.out).slug).toBe('demo')
})

t('--root after -- belongs to the command that exec runs', () => {
  const repo = makeRepo()
  const r = sh(repo, ['bash', RS_SH, 'exec', '--timeout', '5', '--', 'sh', '-c', 'echo "$@"', 'x', '--root', '/nonexistent'])
  expect(r.code).toBe(0)
  expect(r.out).toContain('--root /nonexistent')
})

t('--root with a missing directory is an error with exit code 2', () => {
  const repo = makeRepo()
  const r = sh(repo, ['bash', RS_SH, 'config', '--root', join(repo, 'nope')])
  expect(r.code).toBe(2)
  expect(r.err).toContain('--root is not a directory')
})
