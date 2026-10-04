import { afterEach, expect, test } from 'bun:test'
import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

const SCRIPTS = join(import.meta.dir, '..', 'skills', 'ratchet', 'scripts')
const RS_SH = join(SCRIPTS, 'ratchet.sh')
const NIGHTLY = join(SCRIPTS, 'dream-nightly.sh')
const FIX = join(import.meta.dir, 'fixtures', 'dream')
const R = '.claude/ratchet'
const EV = `${R}/evidence`
const BUNDLE = '2026-10-05'

// Every test gets its own git repo and its own fake home, so no test touches the real ~.
const dirs: string[] = []
const homes = new Map<string, string>()
afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true })
  homes.clear()
})

// bun's default timeout is 5 s; each RS call starts bash and Python, so allow more.
const t = (name: string, fn: () => void) => test(name, fn, 60_000)

function sh(cwd: string, cmd: string[], env: Record<string, string> = {}) {
  const home = homes.get(cwd)
  const p = Bun.spawnSync(cmd, {
    cwd, stdout: 'pipe', stderr: 'pipe',
    env: { ...process.env, ...(home ? { RATCHET_HOME: home, HOME: home } : {}), ...env },
  })
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

const dream = (repo: string, step: string, ...args: string[]) => rs(repo, 'dream', step, ...args)

function put(repo: string, rel: string, content: string) {
  mkdirSync(dirname(join(repo, rel)), { recursive: true })
  writeFileSync(join(repo, rel), content)
}

function copy(repo: string, from: string, to: string) {
  mkdirSync(dirname(join(repo, to)), { recursive: true })
  cpSync(join(FIX, from), join(repo, to))
}

const read = (repo: string, rel: string) => readFileSync(join(repo, rel), 'utf8')
const json = (repo: string, rel: string) => JSON.parse(read(repo, rel))

// The real paths: git prints /private/var/... for a repo made under /var/... on macOS.
function makeRepo(dreamConfig: Record<string, unknown> = {}) {
  const repo = realpathSync(mkdtempSync(join(tmpdir(), 'dream-')))
  const home = realpathSync(mkdtempSync(join(tmpdir(), 'dream-home-')))
  dirs.push(repo, home)
  homes.set(repo, home)
  sh(repo, ['git', 'init', '-q'])
  put(repo, `${R}/config.json`, JSON.stringify({ version: 2, behavior: { one: 'true', all: 'true' }, dream: dreamConfig }, null, 2))
  return repo
}

const finding = (id: string, issue: string, extra: Record<string, unknown> = {}) => ({
  id, role: 'arch', severity: 'high', issue, fix: 'inset', ruleExists: true, class: 'blocking', ...extra,
})

function triage(repo: string, slug: string, cp: string, findings: unknown[]) {
  put(repo, `${EV}/${slug}/${cp}/3-triage-r1.json`, JSON.stringify({ round: 1, archRan: true, findings }))
}

// A repo with a learnings file, a rejected item, and the evidence that the curate candidates cite.
function curateRepo(dreamConfig: Record<string, unknown> = {}) {
  const repo = makeRepo(dreamConfig)
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  copy(repo, 'rejected.jsonl', `${R}/dreams/rejected.jsonl`)
  copy(repo, 'human-cp5.md', `${EV}/demo/cp5/4-human.md`)
  for (const cp of ['cp1', 'cp2']) {
    triage(repo, 'demo', cp, [finding(`${cp}-A1-1`, 'Field hidden under the keyboard', { rule: 'L-001' }),
      finding(`${cp}-A1-2`, 'Another field hidden', { rule: 'L-001' })])
  }
  const h = dream(repo, 'harvest')
  expect(h.code).toBe(0)
  return { repo, bundle: h.json.bundle as string }
}

function proposal(repo: string, bundle: string, items: unknown[]) {
  put(repo, `${R}/dreams/${bundle}/proposal.json`, JSON.stringify({ version: 1, bundle, items }))
}

const item = (id: string, over: Record<string, unknown> = {}) => ({
  id, op: 'ADD', target: null, scope: 'mobile/**/*.kt',
  rule: 'Dismiss the keyboard from every native text field.',
  check: 'A UI test taps outside the field and expects no focus.',
  evidence: ['demo/cp5/4-human.md:3', 'demo/cp1/3-triage-r1.json'], rows: 3, human: true, reason: '3 rows, human evidence',
  ...over,
})

t('harvest scrubs secrets, cuts long text, and counts the blocking findings that cite a rule', () => {
  const repo = makeRepo()
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  // Built at run time, so that no secret-shaped text sits in the repo for a scanner to find.
  const token = 'ghp_' + 'a1B2c3D4e5'.repeat(4)
  const key = 'sk-' + 'ant-api03-' + 'x'.repeat(24)
  const aws = 'AKIA' + 'ABCDEFGHIJKLMNOP'
  const pw = 'pass' + 'word=' + 'hunter2'
  put(repo, `${EV}/demo/cp1/4-human.md`,
    `> approved, but my env has ${token} and ${pw}\n> keyboard covers the field ${'again '.repeat(400)}\n`)
  triage(repo, 'demo', 'cp1', [
    finding('cp1-A1-1', `Field hidden under the keyboard (L-001), key ${key} and ${aws}`, { rule: 'L-001' }),
    finding('cp1-A1-2', 'A second field is hidden', { rule: 'L-001' }),
    finding('cp1-A1-3', 'Naming', { rule: 'L-002', class: 'advisory', severity: 'low' }),
    finding('cp1-B1-1', 'Crash on rotate, see L-003', { role: 'break', proofResult: { result: 'reproduced' } }),
  ])
  triage(repo, 'demo', 'cp2', [finding('cp2-A1-1', 'Hidden again', { rule: 'L-001' })])

  const r = dream(repo, 'harvest')
  expect(r.code).toBe(0)
  expect(r.json).toMatchObject({ ok: true, cmd: 'dream harvest', verdict: 'pass', new: 3, counts: { human: 1, reviews: 2, findings: 5 } })
  const text = read(repo, r.json.evidence)
  for (const secret of [token, key, aws, 'hunter2']) expect(text).not.toContain(secret)
  expect(text).toContain('[redacted]')

  const h = JSON.parse(text)
  expect(h.human[0].lines.map((l: any) => l.text.length).every((n: number) => n <= 600)).toBe(true)
  const by = Object.fromEntries(h.learnings.entries.map((e: any) => [e.id, e]))
  // L-001: one finding counts once, although it names the rule in `rule` and in its text.
  expect(by['L-001'].helpful).toBe(3)
  expect(by['L-002']).toMatchObject({ helpful: 0, cited: { blocking: 0, advisory: 1 } })
  expect(by['L-003'].helpful).toBe(1)
  expect(h.ruleCitations['L-001']).toEqual({ blocking: 3, advisory: 0 })
})

t('harvest reads version 1 evidence names, plans and learnings, and skips what is not evidence', () => {
  const repo = makeRepo()
  copy(repo, 'learnings.v1.md', `${R}/learnings.md`)
  copy(repo, 'plan.v1.md', `${R}/plans/ios.md`)
  copy(repo, 'plan.v2.md', `${R}/plans/demo.md`)
  copy(repo, 'plan.reference.md', `${R}/plans/ios.reference.md`)
  put(repo, `${R}/plans/broken.md`, '# no table here\n')
  const files = ['3-review-arch-r1.json', '3-review-break-r1.json', '3-break-r2.json', '3-review-break-r2.json',
    '4-human.md', '4-human-r1.md', '0-amendments.md', 'decisions.md']
  for (const f of files) copy(repo, `evidence-v1/${f}`, `${EV}/ios/cp2/${f}`)
  // A screenshot that the human gate named like its text, a pin, and a pinned copy: none is evidence.
  writeFileSync(join(repo, `${EV}/ios/cp2/4-human-r1-shot.png`), Buffer.from([0x89, 0x50, 0x4e, 0x47, 0, 255, 254]))
  put(repo, `${EV}/ios/_state/spec.lock`, '')
  put(repo, `${EV}/ios/cp2/locked/x/3-review-arch-r9.json`, '{"findings":[{"id":"Z"}]}')

  const r = dream(repo, 'harvest')
  expect(r.code).toBe(0)
  const h = JSON.parse(read(repo, r.json.evidence))
  const names = (docs: any[]) => docs.map(d => d.path.split('/').pop()).sort()
  expect(names(h.human)).toEqual(['4-human-r1.md', '4-human.md'])
  // The v2 name (3-break-r2) wins over the v1 name of the same round, as gate b3 reads them.
  expect(names(h.reviews)).toEqual(['3-break-r2.json', '3-review-arch-r1.json', '3-review-break-r1.json'])
  const findings = h.reviews.flatMap((d: any) => d.findings)
  expect(findings.map((f: any) => f.id).sort()).toEqual(['A3', 'B5', 'B7'])
  expect(findings.every((f: any) => f.class === 'unknown')).toBe(true)
  expect(findings.find((f: any) => f.id === 'B7').proof).toBe('given')
  expect(h.amendments).toHaveLength(1)
  expect(h.decisions).toHaveLength(1)

  const plans = Object.fromEntries(h.plans.map((p: any) => [p.slug, p]))
  expect(Object.keys(plans).sort()).toEqual(['demo', 'ios'])
  expect(h.warnings.join(' ')).toContain('broken.md')
  expect(plans.ios.rows.map((x: any) => x.status)).toEqual(['approved', 'blocked', 'todo'])
  expect(plans.ios.rows[1].notes.map((n: any) => n.text).join(' ')).toContain('Needs human decision')
  expect(plans.ios.rows[1].rounds).toEqual({ b3: 2 })
  expect(plans.ios.rows[0].notes[0].text).toContain('waive(cp1)')
  expect(plans.demo.counts).toEqual({ 'approved-unverified': 1, superseded: 1, blocked: 1 })
  expect(h.learnings.entries).toEqual([])
  expect(h.learnings.v1).toHaveLength(3)
  expect(h.learnings.v1[0].text).not.toContain('2026-10-02')
})

t('curate drops weak, duplicate and rejected candidates, keeps an EDIT near its own target, and caps the rest', () => {
  const { repo, bundle } = curateRepo()
  copy(repo, 'candidates.curate.json', `${R}/dreams/${bundle}/candidates.json`)
  const c = dream(repo, 'curate', bundle)
  expect(c.code).toBe(0)
  expect(c.json).toMatchObject({ verdict: 'pass', items: 3, candidates: 7, dropped: { weak: 1, duplicate: 1, rejected: 1, cap: 1 } })

  const p = json(repo, c.json.proposal)
  expect(p.items.map((i: any) => [i.id, i.op, i.target, i.newId])).toEqual(
    [['P1', 'ADD', null, 'L-005'], ['P2', 'EDIT', 'L-001', null], ['P3', 'ADD', null, 'L-006']])
  // The ref `cp5/4-human.md:3` names no plan; it still finds the file, and a human file counts.
  expect(p.items[0]).toMatchObject({
    rows: 3, human: true,
    evidence: ['demo/cp5/4-human.md:3', 'demo/cp1/3-triage-r1.json#cp1-A1-1', 'demo/cp2/3-triage-r1.json#cp2-A1-1'],
  })
  expect(p.items[1].rule).toContain('small screen')

  const md = read(repo, `${R}/dreams/${bundle}/proposal.md`)
  expect(md.split('\n')[0]).toBe(`Dream ${bundle}: 3 proposals`)
  expect(md).toContain('1. ADD L-005 (mobile/**/*.kt): Dismiss the keyboard')
  expect(md).toContain('2. EDIT L-001 (mobile/**)')
  expect(md.trimEnd().split('\n').length).toBeLessThanOrEqual(2 + 3 * 3)

  const why = read(repo, c.json.evidence)
  expect(why).toContain('drop weak ADD: one row and no human evidence')
  expect(why).toContain('drop duplicate ADD: near-duplicate of L-002')
  expect(why).toContain('drop rejected ADD: matches an item that the human rejected on 2026-10-03')
  expect(why).toContain('drop cap ADD: over the limit of 3 items')
  expect(json(repo, `${R}/dreams/last.json`)).toMatchObject({ bundle, items: 3 })
})

t('curate checks the shape of each candidate, lets one human line carry a single row, and settles conflicts', () => {
  const { repo, bundle } = curateRepo({ maxItems: 10 })
  const base = { scope: 'mobile/**', check: 'A test checks it.', evidence: ['cp5/4-human.md:4'], rows: 1 }
  const words = Array.from({ length: 41 }, (_, i) => `word${i}`).join(' ')
  const candidates = [
    { ...base, op: 'ADD', rule: 'Show the reconnecting banner when the socket drops.' },
    { ...base, op: 'ADD', rule: 'A rule without a check.', check: '' },
    { ...base, op: 'ADD', rule: words },
    { ...base, op: 'ADD', rule: 'A rule with a bad glob.', scope: 'src/**/*.{kt,swift}' },
    { ...base, op: 'RETIRE', target: 'L-099', rule: 'The target does not exist.' },
    { ...base, op: 'RETIRE', target: 'L-002', rule: 'No finding cited it in 9 rows.', rows: 9 },
    { ...base, op: 'EDIT', target: 'L-002', rule: 'Log the request ID and the user on each error path.', check: 'Each catch block logs both.', rows: 2 },
    { ...base, op: 'MERGE', target: ['L-003', 'L-004'], scope: 'mobile/**/*.kt, docs/**', rows: 2,
      rule: 'Keep the screen on a disconnect, and write one verb for each requirement.' },
    { ...base, op: 'MERGE', target: 'L-001, L-003', rows: 2, rule: 'Check fields and keep the screen on a disconnect.' },
    { ...base, op: 'ADD', rule: `Never log ${'pass' + 'word=' + 'hunter2'}.` },
    { ...base, op: 'ADD', rule: 'Keep status: retired out of a rule.' },
    { ...base, op: 'FOO', rule: 'An op that does not exist.' },
    { ...base, op: 'ADD', rule: 'A rule whose evidence is missing.', evidence: ['nope/4-human.md:1'] },
  ]
  put(repo, `${R}/dreams/${bundle}/candidates.json`, JSON.stringify({ candidates }))
  const c = dream(repo, 'curate', bundle)
  expect(c.code).toBe(0)
  expect(c.json.dropped).toEqual({ invalid: 7, evidence: 1, conflict: 2 })

  const p = json(repo, c.json.proposal)
  // RETIRE has 9 rows and wins L-002 over the EDIT. The MERGE of L-003 and L-004 wins L-003 over the other MERGE.
  expect(p.items.map((i: any) => [i.id, i.op, i.target])).toEqual(
    [['P1', 'RETIRE', 'L-002'], ['P2', 'MERGE', ['L-003', 'L-004']], ['P3', 'ADD', null]])
  expect(p.items[2]).toMatchObject({ rows: 1, human: true, reason: '1 row, human evidence' })
  const why = read(repo, c.json.evidence)
  expect(why).toContain('the rule has 41 words; the limit is 40')
  expect(why).toContain('braces are not supported')
  expect(why).toContain('target L-099 not found')
  expect(why).toContain('the rule holds a secret')
  expect(why).toContain('L-002 is also changed by a better candidate')
})

t('curate treats a ref that two plans share as one file that exists, and never as two rows', () => {
  const repo = makeRepo()
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  for (const slug of ['a', 'b']) {
    copy(repo, 'human-cp5.md', `${EV}/${slug}/cp5/4-human.md`)
    triage(repo, slug, 'cp5', [finding('cp5-A1-1', 'Hidden field', { rule: 'L-001' })])
  }
  const h = dream(repo, 'harvest')
  const base = { op: 'ADD', target: null, scope: 'mobile/**', check: 'A test checks it.', counter: [], rows: 1 }
  put(repo, `${R}/dreams/${h.json.bundle}/candidates.json`, JSON.stringify({
    candidates: [
      // The second ref could be a/cp5 or b/cp5. Counting it as a row of its own would pass the two-row gate.
      { ...base, rule: 'Pin each feature flag default in a test.', evidence: ['b/cp5/3-triage-r1.json', 'cp5/3-triage-r1.json'] },
      // Both human files match, so the ref is human, but it names no row.
      { ...base, rule: 'Show the reconnecting banner when the socket drops.', evidence: ['cp5/4-human.md:4'] },
    ],
  }))
  const c = dream(repo, 'curate', h.json.bundle)
  expect(c.json).toMatchObject({ verdict: 'pass', items: 1, dropped: { weak: 1 } })
  const p = json(repo, c.json.proposal)
  expect(p.items[0]).toMatchObject({ rows: 1, human: true, evidence: ['cp5/4-human.md:4'] })
})

t('curate takes the JSON from reflect.log when the reflection could not write candidates.json', () => {
  const { repo, bundle } = curateRepo()
  const dir = `${R}/dreams/${bundle}`
  const none = dream(repo, 'curate', bundle)
  expect(none.code).toBe(2)
  expect(none.json.summary).toContain('wrote nothing')

  const answer = {
    candidates: [{
      op: 'ADD', target: null, scope: 'mobile/**', rule: 'Show the reconnecting banner when the socket drops.',
      check: 'A test drops the socket and expects the banner.', evidence: ['cp5/4-human.md:4'], counter: [], rows: 1,
    }],
  }
  put(repo, `${dir}/reflect.log`, `I read the harvest.\n\`\`\`json\n${JSON.stringify(answer, null, 2)}\n\`\`\`\nA stray {brace}.\n`)
  const c = dream(repo, 'curate', bundle)
  expect(c.code).toBe(0)
  expect(c.json).toMatchObject({ verdict: 'pass', items: 1 })
  expect(json(repo, `${dir}/candidates.json`)).toEqual(answer)
  expect(read(repo, c.json.evidence)).toContain('come from reflect.log')
})

t('apply ADD takes the next free ID, sets the origin, and keeps every other byte of learnings.md', () => {
  const repo = makeRepo()
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  const before = read(repo, `${R}/learnings.md`)
  proposal(repo, BUNDLE, [item('P1'), item('P2', { rule: 'Second rule.' })])

  const undecided = dream(repo, 'apply', BUNDLE, '--accept', 'P1')
  expect(undecided.code).toBe(2)
  expect(undecided.json.summary).toContain('P2')
  expect(read(repo, `${R}/learnings.md`)).toBe(before)

  const ok = dream(repo, 'apply', BUNDLE, '--accept', 'P1', '--reject', 'P2', '--reason', 'too vague')
  expect(ok.code).toBe(0)
  expect(ok.json).toMatchObject({ verdict: 'pass', accepted: [{ id: 'P1', op: 'ADD', entry: 'L-005' }], rejected: ['P2'] })
  const entry = '### L-005\n- scope: mobile/**/*.kt\n- rule: Dismiss the keyboard from every native text field.\n'
    + '- check: A UI test taps outside the field and expects no focus.\n'
    + '- source: demo/cp5/4-human.md:3, demo/cp1/3-triage-r1.json\n- origin: dream\n'
    + '- helpful: 0 · harmful: 0 · status: active\n'
  expect(read(repo, `${R}/learnings.md`)).toBe(`${before}\n${entry}`)
  // The real consumer finds the new entry by its scope.
  expect(sh(repo, ['bash', RS_SH, 'learnings', '--scope', 'mobile/app/Form.kt']).out).toContain('L-005')
  expect(json(repo, `${R}/dreams/${BUNDLE}/review.json`)).toMatchObject({ accepted: [{ id: 'P1', entry: 'L-005' }], rejected: ['P2'] })

  const again = dream(repo, 'apply', BUNDLE, '--accept', 'P1', '--reject', 'P2')
  expect(again.code).toBe(2)
  expect(again.json.summary).toContain('reviewed already')
  expect(read(repo, `${R}/learnings.md`).match(/### L-005/g)).toHaveLength(1)

  // A version 1 file keeps its bullets byte for byte. RS learnings ignores bullets outside entries, so apply warns.
  const old = makeRepo()
  copy(old, 'learnings.v1.md', `${R}/learnings.md`)
  proposal(old, BUNDLE, [item('P1')])
  const v1 = dream(old, 'apply', BUNDLE, '--accept', 'P1')
  expect(v1.json.warnings).toEqual(['3 bullet(s) of learnings.md sit outside any entry, and RS learnings ignores them'])
  expect(read(old, `${R}/learnings.md`).startsWith(readFileSync(join(FIX, 'learnings.v1.md'), 'utf8'))).toBe(true)
})

t('apply RETIRE, EDIT and MERGE change only the lines of their entries, and a rejection lands in rejected.jsonl', () => {
  const repo = makeRepo()
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  const before = read(repo, `${R}/learnings.md`)
  const items = [
    item('P1', { op: 'RETIRE', target: 'L-002', rule: 'No finding cited it.', scope: null, check: '' }),
    item('P2', { op: 'EDIT', target: 'L-001', scope: 'mobile/**, ios/**', rule: 'Check each text field with the keyboard open, on a device.', check: 'The device pack lists each text field.' }),
    item('P3', { op: 'MERGE', target: ['L-003', 'L-004'], scope: 'mobile/**/*.kt, docs/**', rule: 'Keep the screen on a disconnect, and write one verb for each requirement.', check: 'A test and the doc linter both pass.' }),
    item('P4', { rule: 'Will be rejected.' }),
  ]

  // A bad answer changes nothing: an unknown ID, an ID in both lists, and an item whose target is gone.
  proposal(repo, '2026-10-04', [item('P1'), item('P2', { op: 'RETIRE', target: 'L-099', rule: 'Gone.' })])
  expect(dream(repo, 'apply', '2026-10-04', '--accept', 'P9', '--reject', 'P1,P2').code).toBe(2)
  expect(dream(repo, 'apply', '2026-10-04', '--accept', 'P1', '--reject', 'P1,P2').code).toBe(2)
  expect(dream(repo, 'apply', '2026-10-04', '--accept', 'P1,P2').code).toBe(2)
  expect(read(repo, `${R}/learnings.md`)).toBe(before)
  expect(existsSync(join(repo, `${R}/dreams/2026-10-04/review.json`))).toBe(false)

  proposal(repo, BUNDLE, items)
  const r = dream(repo, 'apply', BUNDLE, '--accept', 'P1,P2', '--accept', 'P3', '--reject', 'P4', '--reason', 'too vague')
  expect(r.code).toBe(0)
  expect(r.json.accepted).toEqual([
    { id: 'P1', op: 'RETIRE', entry: 'L-002' }, { id: 'P2', op: 'EDIT', entry: 'L-001' }, { id: 'P3', op: 'MERGE', entry: 'L-003' }])

  const expected = before
    .replace('status: active\n\n### L-003', 'status: retired\n\n### L-003')
    .replace('- scope: mobile/**\n- rule: Check each text field with the keyboard open, on a device or a simulator.\n- check: The device check pack lists each new text field.\n',
      '- scope: mobile/**, ios/**\n- rule: Check each text field with the keyboard open, on a device.\n- check: The device pack lists each text field.\n')
    .replace('- scope: mobile/**/*.kt\n- rule: Keep the screen on a transient disconnect and show a reconnecting banner.\n- check: A test drives a disconnect and expects the same screen.\n',
      '- scope: mobile/**/*.kt, docs/**\n- rule: Keep the screen on a disconnect, and write one verb for each requirement.\n- check: A test and the doc linter both pass.\n')
    .replace('status: active\n\n## Notes', `status: retired\n- note: merged into L-003 by dream ${BUNDLE}\n\n## Notes`)
  expect(read(repo, `${R}/learnings.md`)).toBe(expected)

  const rejected = read(repo, `${R}/dreams/rejected.jsonl`).trim().split('\n').map(l => JSON.parse(l))
  expect(rejected).toHaveLength(1)
  expect(rejected[0]).toMatchObject({ bundle: BUNDLE, op: 'ADD', rule: 'Will be rejected.', reason: 'too vague' })
  expect(rejected[0].date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  // The retired entry no longer reaches an agent, and the merged one does.
  const seen = sh(repo, ['bash', RS_SH, 'learnings', '--scope', 'server/x.ts', 'docs/a.md']).out
  expect(seen).not.toContain('L-002')
  expect(seen).not.toContain('L-004')
  expect(seen).toContain('L-003')
})

t('apply pins learnings.md again in each plan, and leaves every other pin and every stale pin alone', () => {
  const repo = makeRepo()
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  const state = `${EV}/demo/_state`
  put(repo, `${R}/list.txt`, `${R}/config.json\n${R}/learnings.md\n`)
  expect(sh(repo, ['bash', RS_SH, 'lock', state, '--from', `${R}/list.txt`]).code).toBe(0)
  const check = () => sh(repo, ['bash', RS_SH, 'check', state])
  expect(check().code).toBe(0)

  proposal(repo, BUNDLE, [item('P1')])
  const r = dream(repo, 'apply', BUNDLE, '--accept', 'P1')
  expect(r.json).toMatchObject({ verdict: 'pass', relocked: 1, stalePins: [] })
  expect(check()).toMatchObject({ code: 0 })

  // Only learnings.md is pinned again. A later edit of the config must still stop gate b1.
  const config = read(repo, `${R}/config.json`)
  writeFileSync(join(repo, `${R}/config.json`), config + '\n')
  const tampered = check()
  expect(tampered.code).toBe(1)
  expect(tampered.out).toContain('config.json')
  expect(tampered.out).not.toContain('learnings.md')
  writeFileSync(join(repo, `${R}/config.json`), config)
  expect(check().code).toBe(0)

  // Someone edited learnings.md before the apply. That edit was never reviewed, so the pin stays stale.
  writeFileSync(join(repo, `${R}/learnings.md`), read(repo, `${R}/learnings.md`) + '\nAn edit that nobody reviewed.\n')
  proposal(repo, '2026-10-06', [item('P1', { rule: 'Another rule.' })])
  const stale = dream(repo, 'apply', '2026-10-06', '--accept', 'P1')
  expect(stale.json).toMatchObject({ verdict: 'pass', relocked: 0, stalePins: [state] })
  const still = check()
  expect(still.code).toBe(1)
  expect(still.out).toContain('learnings.md')
})

t('install writes the launchd plist and the repo list under RATCHET_HOME, and uninstall removes the plist', () => {
  const repo = makeRepo({ nightly: true })
  const home = homes.get(repo)!
  const plist = join(home, 'Library', 'LaunchAgents', 'com.ratchet.dream.plist')

  const i = dream(repo, 'install')
  expect(i.code).toBe(0)
  expect(i.json).toMatchObject({ verdict: 'pass', loaded: false, repoAdded: true })
  expect(i.json.command).toContain('launchctl bootstrap gui/')
  expect(Buffer.byteLength(i.out.trimEnd())).toBeLessThanOrEqual(1024)
  const xml = readFileSync(plist, 'utf8')
  const log = join(home, '.claude', 'ratchet', 'dream.log')
  for (const s of ['<string>com.ratchet.dream</string>', '<string>/bin/bash</string>', 'dream-launch.sh',
    '<key>Hour</key>', '<integer>3</integer>', '<key>Minute</key>', '<integer>30</integer>', `<string>${log}</string>`]) {
    expect(xml).toContain(s)
  }
  // The plugin path holds its version, so the plist names a launcher that finds the newest one.
  expect(readFileSync(join(home, '.claude', 'ratchet', 'dream-launch.sh'), 'utf8')).toContain(NIGHTLY)
  expect(xml).not.toMatch(/token|secret|password|api[_-]?key/i)
  expect(json(home, '.claude/ratchet/repos.json').repos).toEqual([repo])
  expect(dream(repo, 'register').json).toMatchObject({ added: false, repos: 1 })

  const u = dream(repo, 'uninstall')
  expect(u.json).toMatchObject({ verdict: 'pass', removed: true, unloaded: false })
  expect(u.json.command).toContain('launchctl bootout gui/')
  expect(existsSync(plist)).toBe(false)
})

t('the nightly script harvests, runs claude with a budget and a short tool list, curates, and then waits for the review', () => {
  const repo = makeRepo({ nightly: true, budgetUsd: 2 })
  const home = homes.get(repo)!
  copy(repo, 'human-cp5.md', `${EV}/demo/cp1/4-human.md`)
  const bin = join(home, 'bin')
  mkdirSync(bin)
  const fake = join(bin, 'claude')
  cpSync(join(FIX, 'fake-claude.sh'), fake)
  chmodSync(fake, 0o755)
  const claudeLog = join(home, 'claude.log')
  const env = {
    RATCHET_HOME: home, HOME: home, RATCHET_CLAUDE: fake, FAKE_CLAUDE_LOG: claudeLog,
    FAKE_CANDIDATES: join(FIX, 'candidates.nightly.json'),
  }
  expect(dream(repo, 'register').code).toBe(0)
  // The script runs from outside any repo, as launchd runs it.
  const run = () => sh(home, ['bash', NIGHTLY], env)

  const first = run()
  expect(first.code).toBe(0)
  expect(first.out.trim().split('\n')).toHaveLength(1)
  expect(first.out).toContain(`${repo}: proposed 1 item(s) in dream`)
  // The prompt comes first because --allowedTools takes a list; the model comes from reflect.md.
  expect(readFileSync(claudeLog, 'utf8').trim().split('\n')).toEqual(
    ['--model', 'sonnet', '--max-budget-usd', '2', '--allowedTools', 'Read Write'])
  const prompt = readFileSync(`${claudeLog}.prompt`, 'utf8')
  expect(prompt).toContain('You read what happened in past ratchet runs')
  expect(prompt).not.toContain('model: sonnet')

  const bundle = readdirSync(join(repo, R, 'dreams')).find(n => /^\d{4}-\d{2}-\d{2}$/.test(n))!
  const p = json(repo, `${R}/dreams/${bundle}/proposal.json`)
  expect(p.items).toHaveLength(1)
  expect(p.items[0]).toMatchObject({ op: 'ADD', newId: 'L-001', human: true, evidence: ['demo/cp1/4-human.md:1'] })
  // The dream proposes only. It never applies a change and never commits.
  expect(existsSync(join(repo, R, 'learnings.md'))).toBe(false)
  expect(sh(repo, ['git', 'rev-parse', '--verify', '-q', 'HEAD']).code).not.toBe(0)

  const waiting = run()
  expect(waiting.out).toContain('skipped, a proposal waits for review')
  expect(readFileSync(`${claudeLog}.calls`, 'utf8').trim().split('\n')).toHaveLength(1)

  expect(dream(repo, 'apply', bundle, '--accept', 'P1').code).toBe(0)
  expect(run().out).toContain('skipped, the last dream is under 20 h old')

  // The window: nothing is new after the dream, and a later file opens the next bundle.
  expect(dream(repo, 'harvest').json).toMatchObject({ new: 0, bundle: null })
  put(repo, `${EV}/demo/cp2/4-human.md`, '> another problem\n')
  const more = dream(repo, 'harvest')
  expect(more.json).toMatchObject({ new: 1, counts: { human: 1 } })
  expect(more.json.bundle).toMatch(/^\d{4}-\d{2}-\d{2}(-2)?$/)
  expect(more.json.bundle).not.toBe(bundle)
})
