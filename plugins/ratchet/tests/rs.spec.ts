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
  expect(r.json.checks.map((c: any) => c.id)).toEqual(['sh-only', 'always', 'behavior'])
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

t('b3 reads version 1 verdicts as advisory', () => {
  const repo = makeRepo()
  copy(repo, 'verdicts/v1-arch.json', `${EV}/3-review-arch-r1.json`)
  copy(repo, 'verdicts/v1-break.json', `${EV}/3-review-break-r1.json`)
  const r = gate(repo, 'b3')
  expect(r.code).toBe(0)
  expect(r.json).toMatchObject({ verdict: 'pass', blocking: [], advisory: ['A1', 'B1', 'B2'], unproven: ['B1', 'B2'], stage: 'B4' })
  expect(rs(repo, 'state', 'demo', 'cp1').json.refs.gated).toMatch(SHA)
})

t('b3 in round 2 proves the open findings again and marks a fixed one addressed', () => {
  const repo = makeRepo()
  put(repo, `${EV}/proofs/p1.sh`, 'if grep -q NotImplemented src/greet.sh; then echo "still broken: NotImplemented"; exit 1; fi\n')
  snapBase(repo)
  const prep1 = gate(repo, 'b3-prep')
  expect(prep1.json).toMatchObject({ verdict: 'pass', structural: true, delta: null, evidence: [] })
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
  expect(r.json.checksMore + r.json.checks.length).toBe(41)
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
