import { afterEach, expect, test } from 'bun:test'
import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, join } from 'node:path'

const SCRIPTS = join(import.meta.dir, '..', 'skills', 'ratchet', 'scripts')
const RS_SH = join(SCRIPTS, 'ratchet.sh')
const NIGHTLY = join(SCRIPTS, 'dream-nightly.sh')
const FIX = join(import.meta.dir, 'fixtures', 'dream')
const SESS = join(FIX, 'sessions')
const R = '.claude/ratchet'
const EV = `${R}/evidence`
const PROJECTS = '.claude/projects'
const BUNDLE = '2026-10-05'

// Every test gets its own fake home (RATCHET_HOME and HOME) and a plain folder to run from. Neither
// is a git repo, because the dream works from any folder. A repo exists only where a test needs one.
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

function rs(cwd: string, ...args: string[]) {
  const r = sh(cwd, ['bash', RS_SH, ...args])
  const json = parse(r.out)
  // A Python traceback lands on stderr; show it when an error left no JSON behind.
  if (r.code === 2 && json === null && r.err) console.error(r.err)
  return { ...r, json }
}

const dream = (cwd: string, step: string, ...args: string[]) => rs(cwd, 'dream', step, ...args)

function put(root: string, rel: string, content: string) {
  mkdirSync(dirname(join(root, rel)), { recursive: true })
  writeFileSync(join(root, rel), content)
}

function copy(root: string, from: string, to: string) {
  mkdirSync(dirname(join(root, to)), { recursive: true })
  cpSync(join(FIX, from), join(root, to))
}

const read = (root: string, rel: string) => readFileSync(join(root, rel), 'utf8')
const json = (root: string, rel: string) => JSON.parse(read(root, rel))
const has = (root: string, rel: string) => existsSync(join(root, rel))

// The real paths: git prints /private/var/... for a folder made under /var/... on macOS.
function makeHome() {
  const home = realpathSync(mkdtempSync(join(tmpdir(), 'dream-home-')))
  const work = realpathSync(mkdtempSync(join(tmpdir(), 'dream-work-')))
  dirs.push(home, work)
  homes.set(home, home)
  homes.set(work, home)
  return { home, work }
}

function makeRepo(home: string) {
  const repo = realpathSync(mkdtempSync(join(tmpdir(), 'dream-repo-')))
  dirs.push(repo)
  homes.set(repo, home)
  sh(repo, ['git', 'init', '-q'])
  put(repo, `${R}/config.json`, JSON.stringify({ version: 2, behavior: { one: 'true', all: 'true' } }, null, 2))
  return repo
}

// ---------------------------------------------------------------- session transcripts

// Built at run time, so that no secret-shaped text sits in the repo for a scanner to find.
const TOKEN = 'ghp_' + 'a1B2c3D4e5'.repeat(4)
const EMAIL = 'someone@' + 'example.com'
const AAA = 'aaaaaaaa-1111-4111-8111-111111111111'
const BBB = 'bbbbbbbb-2222-4222-8222-222222222222'
const FFF = 'ffffffff-3333-4333-8333-333333333333'
const EEE = 'eeeeeeee-4444-4444-8444-444444444444'
const PPP = '99999999-5555-4555-8555-555555555555'
const MULTI = 'dddddddd-6666-4666-8666-666666666666'

function session(home: string, project: string, id: string, from: string) {
  const text = readFileSync(join(SESS, from), 'utf8').replaceAll('__TOKEN__', TOKEN).replaceAll('__EMAIL__', EMAIL)
  put(home, `${PROJECTS}/${project}/${id}.jsonl`, text)
}

function subagent(home: string, project: string, parent: string) {
  for (const f of ['agent-a1b2c3d4e5f6.jsonl', 'agent-a1b2c3d4e5f6.meta.json']) {
    put(home, `${PROJECTS}/${project}/${parent}/subagents/${f}`, readFileSync(join(SESS, 'subagent', f), 'utf8'))
  }
}

const rec = (sid: string, ts: string, cwd: string, extra: Record<string, unknown>) => ({
  parentUuid: null, isSidechain: false, uuid: crypto.randomUUID(), timestamp: ts, userType: 'external',
  entrypoint: 'cli', cwd, sessionId: sid, version: '2.1.0', gitBranch: 'main', ...extra,
})
const humanRec = (sid: string, ts: string, cwd: string, text: string) =>
  rec(sid, ts, cwd, { type: 'user', message: { role: 'user', content: text }, origin: { kind: 'human' }, promptSource: 'typed' })
const asstRec = (sid: string, ts: string, cwd: string, text = 'ok') =>
  rec(sid, ts, cwd, { type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text }] } })

function writeSession(home: string, project: string, sid: string, records: object[]) {
  put(home, `${PROJECTS}/${project}/${sid}.jsonl`, records.map(r => JSON.stringify(r)).join('\n') + '\n')
}

// A dry harvest, which leaves no bundle behind. It returns the summary line and the whole harvest.
function dry(work: string, ...args: string[]) {
  const out = join(work, 'dry.json')
  const r = dream(work, 'harvest', ...args, '--dry', '--out', out)
  return { r, h: r.code === 0 && existsSync(out) ? JSON.parse(readFileSync(out, 'utf8')) : null }
}

// ---------------------------------------------------------------- ratchet evidence

const finding = (id: string, issue: string, extra: Record<string, unknown> = {}) => ({
  id, role: 'arch', severity: 'high', issue, fix: 'inset', ruleExists: true, class: 'blocking', ...extra,
})

function triage(repo: string, slug: string, cp: string, findings: unknown[]) {
  put(repo, `${EV}/${slug}/${cp}/3-triage-r1.json`, JSON.stringify({ round: 1, archRan: true, findings }))
}

// The dream sees a repo only through the working folder of a session. This session has no turn.
function seed(home: string, repo: string) {
  writeSession(home, '-seed-repo', '5eed0000-0000-4000-8000-000000000000', [asstRec('5eed0000-0000-4000-8000-000000000000', new Date().toISOString(), repo)])
}

// A repo with a learnings file, a rejected item, and the evidence that the curate candidates cite.
function curateRepo(dreamConfig: Record<string, unknown> = {}) {
  const { home, work } = makeHome()
  if (Object.keys(dreamConfig).length) put(home, `${R}/dream.json`, JSON.stringify(dreamConfig))
  const repo = makeRepo(home)
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  copy(home, 'rejected.jsonl', `${R}/dreams/rejected.jsonl`)
  copy(repo, 'human-cp5.md', `${EV}/demo/cp5/4-human.md`)
  for (const cp of ['cp1', 'cp2']) {
    triage(repo, 'demo', cp, [finding(`${cp}-A1-1`, 'Field hidden under the keyboard', { rule: 'L-001' }),
      finding(`${cp}-A1-2`, 'Another field hidden', { rule: 'L-001' })])
  }
  seed(home, repo)
  const h = dream(work, 'harvest')
  expect(h.code).toBe(0)
  return { home, work, repo, bundle: h.json.bundle as string }
}

// The 2.0 candidate file named its entry in `target`. The 2.1 shape names the target and the repo.
function ratchetCandidates(file: string, repo: string) {
  const raw = JSON.parse(readFileSync(join(FIX, file), 'utf8'))
  return { candidates: raw.candidates.map(({ rows: _rows, target, ...c }: any) => ({ ...c, target: 'ratchet', repo, id: target })) }
}

function proposal(home: string, bundle: string, items: unknown[]) {
  put(home, `${R}/dreams/${bundle}/proposal.json`, JSON.stringify({ version: 2, bundle, items }))
}

const item = (repo: string, id: string, over: Record<string, unknown> = {}) => ({
  id, op: 'ADD', target: 'ratchet', repo, entry: null, newId: null, scope: 'mobile/**/*.kt',
  rule: 'Dismiss the keyboard from every native text field.',
  check: 'A UI test taps outside the field and expects no focus.',
  evidence: ['demo/cp5/4-human.md:3', 'demo/cp1/3-triage-r1.json'], recurrence: 3, strong: true, reason: '3 rows, human evidence',
  ...over,
})

// ---------------------------------------------------------------- harvest

t('harvest keeps the human turns of a session, tags them, and scrubs secrets and emails', () => {
  const { home, work } = makeHome()
  session(home, '-tmp-demo', AAA, 'human.jsonl')
  const { r, h } = dry(work, '--since', '2026-09-30')
  expect(r.code).toBe(0)
  expect(r.json).toMatchObject({
    verdict: 'pass', dry: true, bundle: null, counts: { turns: 7, sessions: 1 },
    tags: { interrupt: 1, declined: 1, rule: 1, correction: 1, chore: 2 }, dropped: { perSession: 0, size: 0 },
  })
  expect(Buffer.byteLength(r.out.trimEnd())).toBeLessThanOrEqual(1024)

  // Line 7 repeats the queued prompt of line 6 within 5 s. A bare /clear, a compact summary and a plugin
  // message are no human turn. The slash command with arguments is one.
  const by = Object.fromEntries(h.turns.map((x: any) => [x.id, x]))
  expect(Object.keys(by)).toEqual(['aaaaaaaa#2', 'aaaaaaaa#6', 'aaaaaaaa#11', 'aaaaaaaa#13', 'aaaaaaaa#14', 'aaaaaaaa#15', 'aaaaaaaa#19'])
  expect(by['aaaaaaaa#2']).toMatchObject({ project: '-tmp-demo', session: 'aaaaaaaa', cwd: '/tmp/demo', tags: ['rule'], prev: { text: '', tools: [] } })
  expect(by['aaaaaaaa#6']).toMatchObject({ tags: ['chore'], prev: { text: 'I ran the build and the tests pass.', tools: ['Bash: npm test'] } })
  // The turn after an interrupt carries the interrupt tag, and it corrects the agent.
  expect(by['aaaaaaaa#11']).toMatchObject({ tags: ['interrupt', 'correction'], prev: { text: 'Working on the install.', tools: ['Edit: /tmp/demo/src/a.ts'] } })
  // The words after "the user said:" are a turn of their own, not agent friction.
  expect(by['aaaaaaaa#13']).toMatchObject({ text: 'use the dist folder instead', tags: ['declined'], prev: { tools: ['Bash: rm -rf build'] } })
  expect(by['aaaaaaaa#14'].tags).toEqual(['chore'])
  expect(by['aaaaaaaa#15'].text).toBe('/ratchet fix the login bug')
  expect(by['aaaaaaaa#19'].text).toBe('my token is [redacted] and mail me at [email] please')
  expect(h.friction).toEqual([])
  const text = JSON.stringify(h)
  for (const secret of [TOKEN, EMAIL]) expect(text).not.toContain(secret)

  // A dry run leaves no bundle and no marker: not even the dream folder.
  expect(has(home, R)).toBe(false)
})

t('harvest groups agent friction by role, leaves plain exit codes out, skips sdk-cli runs, and honours the exclude list', () => {
  const { home, work } = makeHome()
  session(home, '-tmp-demo', AAA, 'human.jsonl')
  subagent(home, '-tmp-demo', AAA)
  session(home, '-tmp-demo', BBB, 'teammate-break.jsonl')
  session(home, '-tmp-demo', FFF, 'teammate-spec.jsonl')
  session(home, '-tmp-demo', EEE, 'sdk.jsonl')
  session(home, '-tmp-private', PPP, 'private.jsonl')
  put(home, `${R}/dream.json`, JSON.stringify({ exclude: ['-tmp-private'] }))

  const { r, h } = dry(work, '--since', '2026-09-30')
  expect(r.code).toBe(0)
  // The role comes from the agent name first (spec-demo-cp2), then from the first words of the prompt, then from the meta file.
  expect(h.friction.map((g: any) => [g.id, g.role, g.class, g.count, g.sessions.join(), g.head])).toEqual([
    ['F1', 'review-break', 'harness', 2, 'bbbbbbbb', 'File has not been read yet. Read it first before writing to it.'],
    ['F2', 'Explore', 'harness', 1, 'aaaaaaaa', 'File does not exist. Note: your current working directory is <path>'],
    ['F3', 'spec', 'harness', 1, 'ffffffff', 'File has not been read yet. Read it first before writing to it.'],
    ['F4', 'review-break', 'shell', 1, 'bbbbbbbb', 'Exit code N (eval):N: no matches found: src/*.tsx'],
  ])
  expect(h.friction[0].examples.map((e: any) => e.ref)).toEqual(['bbbbbbbb#3', 'bbbbbbbb#6'])
  // A subagent file has its own line numbers, so its refs name the agent.
  expect(h.friction[1].examples[0].ref).toBe('aaaaaaaa/a1b2c3d4#2')
  // The failing test (Exit code 1, FAIL) is no friction, and the sdk-cli run is skipped as a whole.
  expect(h.skipped).toEqual({ unclassifiedErrors: 1, sdkFiles: 1, unreadableFiles: 0, badRecords: 0 })
  expect(r.json.counts).toMatchObject({ frictionGroups: 4, frictionEvents: 5 })
  const text = JSON.stringify(h)
  expect(text).not.toContain('Never ever do this')
  expect(text).not.toContain('FAIL tests')
  expect(h.turns.map((x: any) => x.project)).not.toContain('-tmp-private')

  // The exclude list also matches the working folder of a record.
  put(home, `${R}/dream.json`, JSON.stringify({ exclude: ['/tmp/demo*'] }))
  const again = dry(work, '--since', '2026-09-30')
  expect(again.h.friction).toEqual([])
  expect(again.h.turns.map((x: any) => x.project)).toEqual(['-tmp-private'])
})

t('harvest keeps 20 turns of a session, and cuts the whole harvest to its size cap, with the drops counted', () => {
  const { home, work } = makeHome()
  const sid = 'c0c0c0c0-0000-4000-8000-000000000001'
  const turns = Array.from({ length: 25 }, (_, i) => humanRec(sid, `2026-09-30T10:${String(i).padStart(2, '0')}:00.000Z`, '/tmp/capped',
    i % 8 === 0 ? `Never skip step ${i} of the release` : `Please check part ${i} of the report`))
  writeSession(home, '-tmp-capped', sid, turns)
  const small = dry(work, '--since', '2026-09-29')
  expect(small.r.json.dropped).toEqual({ perSession: 5, size: 0 })
  expect(small.h.turns).toHaveLength(20)
  // The four turns that say "Never" stay, whatever their place.
  expect(small.h.turns.filter((x: any) => x.tags.includes('rule'))).toHaveLength(4)

  // 14 sessions with 20 long turns each are about 290 KB. The harvest drops the oldest plain turns first.
  const big = makeHome()
  for (let s = 0; s < 14; s++) {
    const id = `b16b16${String(s).padStart(2, '0')}-0000-4000-8000-000000000000`
    writeSession(big.home, '-tmp-big', id, Array.from({ length: 20 }, (_, i) =>
      humanRec(id, `2026-09-30T11:${String(i).padStart(2, '0')}:${String(s).padStart(2, '0')}.000Z`, '/tmp/big',
        `Request ${s}-${i}: ${'lorem ipsum dolor '.repeat(40)}`)))
  }
  const r = dry(big.work, '--since', '2026-09-29')
  expect(r.r.json.dropped.perSession).toBe(0)
  expect(r.r.json.dropped.size).toBeGreaterThan(20)
  expect(r.r.json.size).toBeLessThanOrEqual(150_000)
  expect(r.h.turns.length + r.r.json.dropped.size).toBe(280)
  expect(r.h.dropped.sizeBy).toEqual({ turns: r.r.json.dropped.size, ratchet: 0, friction: 0 })
})

t('the window follows record timestamps across a multi-day file, and the marker moves only after curate', () => {
  const { home, work } = makeHome()
  session(home, '-tmp-multi', MULTI, 'multiday.jsonl')
  const ids = (since: string) => dry(work, '--since', since).h.turns.map((x: any) => x.id)
  expect(ids('2026-09-28')).toEqual(['dddddddd#1', 'dddddddd#2', 'dddddddd#3'])
  expect(ids('2026-09-30T00:00:00Z')).toEqual(['dddddddd#2', 'dddddddd#3'])
  expect(ids('2026-10-02')).toEqual(['dddddddd#3'])

  const h = dream(work, 'harvest', '--since', '2026-09-28')
  expect(h.json).toMatchObject({ new: 3, since: '2026-09-28T00:00:00Z' })
  const bundle = h.json.bundle as string
  expect(bundle).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  expect(has(home, `${R}/dreams/${bundle}/context/rejected.jsonl`)).toBe(true)
  // A harvest does not move the marker, and neither does a curate that fails.
  expect(has(home, `${R}/dreams/last.json`)).toBe(false)
  expect(dream(work, 'curate', bundle).code).toBe(2)
  expect(has(home, `${R}/dreams/last.json`)).toBe(false)

  put(home, `${R}/dreams/${bundle}/candidates.json`, JSON.stringify({ candidates: [{
    op: 'ADD', target: 'project', project: '-tmp-multi', rule: 'Add the section that the human names, in the order given.',
    why: 'Two requests asked for a section.', evidence: ['dddddddd#1', 'dddddddd#2'] }] }))
  const c = dream(work, 'curate', bundle)
  expect(c.code).toBe(0)
  expect(json(home, `${R}/dreams/last.json`)).toMatchObject({ bundle, items: 1 })
  // The window now starts at the marker, and nothing is newer.
  expect(dream(work, 'harvest').json).toMatchObject({ new: 0, bundle: null })
  expect(dream(work, 'state').json).toMatchObject({ state: 'pending', pending: 1, bundle })
})

t('harvest scrubs the ratchet evidence, cuts long text, and counts the blocking findings that cite a rule', () => {
  const { home, work } = makeHome()
  const repo = makeRepo(home)
  seed(home, repo)
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  const key = 'sk-' + 'ant-api03-' + 'x'.repeat(24)
  const aws = 'AKIA' + 'ABCDEFGHIJKLMNOP'
  const pw = 'pass' + 'word=' + 'hunter2'
  put(repo, `${EV}/demo/cp1/4-human.md`,
    `> approved, but my env has ${TOKEN} and ${pw}\n> keyboard covers the field ${'again '.repeat(400)}\n`)
  triage(repo, 'demo', 'cp1', [
    finding('cp1-A1-1', `Field hidden under the keyboard (L-001), key ${key} and ${aws}`, { rule: 'L-001' }),
    finding('cp1-A1-2', 'A second field is hidden', { rule: 'L-001' }),
    finding('cp1-A1-3', 'Naming', { rule: 'L-002', class: 'advisory', severity: 'low' }),
    finding('cp1-B1-1', 'Crash on rotate, see L-003', { role: 'break', proofResult: { result: 'reproduced' } }),
  ])
  triage(repo, 'demo', 'cp2', [finding('cp2-A1-1', 'Hidden again', { rule: 'L-001' })])

  const r = dream(work, 'harvest')
  expect(r.code).toBe(0)
  expect(r.json).toMatchObject({ ok: true, cmd: 'dream harvest', verdict: 'pass', new: 3, counts: { turns: 0, ratchetRepos: 1, ratchetNew: 3 } })
  const text = read(home, r.json.evidence)
  for (const secret of [TOKEN, key, aws, 'hunter2']) expect(text).not.toContain(secret)
  expect(text).toContain('[redacted]')

  const sec = JSON.parse(text).ratchet[repo]
  expect(sec.counts).toMatchObject({ human: 1, reviews: 2, findings: 5 })
  expect(sec.human[0].lines.map((l: any) => l.text.length).every((n: number) => n <= 600)).toBe(true)
  const by = Object.fromEntries(sec.learnings.entries.map((e: any) => [e.id, e]))
  // L-001: one finding counts once, although it names the rule in `rule` and in its text.
  expect(by['L-001'].helpful).toBe(3)
  expect(by['L-002']).toMatchObject({ helpful: 0, cited: { blocking: 0, advisory: 1 } })
  expect(by['L-003'].helpful).toBe(1)
  expect(sec.ruleCitations['L-001']).toEqual({ blocking: 3, advisory: 0 })
  // The reflection reads these through the bundle: the learnings of the repo and a map from its number.
  const ctx = `${R}/dreams/${r.json.bundle}/context`
  expect(json(home, `${ctx}/ratchet-map.json`)).toEqual({ 1: repo })
  expect(read(home, `${ctx}/ratchet-1-learnings.md`)).toBe(read(repo, `${R}/learnings.md`))
})

t('harvest reads version 1 evidence names, plans and learnings, and skips what is not evidence', () => {
  const { home, work } = makeHome()
  const repo = makeRepo(home)
  seed(home, repo)
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

  const r = dream(work, 'harvest')
  expect(r.code).toBe(0)
  const h = JSON.parse(read(home, r.json.evidence)).ratchet[repo]
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

t('the bundle holds the context that the sealed reflection may read: rules, memory index, learnings, rejected items', () => {
  const { home, work } = makeHome()
  session(home, '-tmp-demo', AAA, 'human.jsonl')
  put(home, `${PROJECTS}/-tmp-demo/memory/MEMORY.md`, '- [existing](existing.md) — an older note\n')
  put(home, '.claude/rules/dream/G-001-first.md', '---\ndream-id: G-001\nsource: 2026-10-01\nadded: 2026-10-01\n---\nKeep the first rule.\n\nWhy: a test\n')
  put(home, '.claude/rules/notes.md', 'A hand-written rule that the dream does not own.\n')
  copy(home, 'rejected.jsonl', `${R}/dreams/rejected.jsonl`)
  const r = dream(work, 'harvest', '--since', '2026-09-30')
  const ctx = `${R}/dreams/${r.json.bundle}/context`
  expect(read(home, `${ctx}/global-rules.md`)).toContain('## G-001 (G-001-first.md)')
  expect(read(home, `${ctx}/global-rules.md`)).toContain('Keep the first rule.')
  expect(read(home, `${ctx}/global-rules.md`)).not.toContain('hand-written')
  expect(read(home, `${ctx}/memory--tmp-demo.md`)).toContain('an older note')
  expect(read(home, `${ctx}/rejected.jsonl`)).toContain('theme provider')
  // The hash that curate checks sits beside the bundle, where the reflection cannot write.
  expect(has(home, `${R}/dreams/${r.json.bundle}.harvest.sha256`)).toBe(true)
  const h = json(home, `${R}/dreams/${r.json.bundle}/harvest.json`)
  expect(h.projects).toEqual({ '-tmp-demo': { cwd: '/tmp/demo', turns: 7, sessions: 1 } })

  // The reflection may write inside its folder. A changed harvest is refused, not curated.
  writeFileSync(join(home, `${R}/dreams/${r.json.bundle}/harvest.json`), JSON.stringify({ ...h, projects: { '-tmp-evil': { cwd: '/', turns: 9, sessions: 9 } } }))
  put(home, `${R}/dreams/${r.json.bundle}/candidates.json`, JSON.stringify({ candidates: [] }))
  const c = dream(work, 'curate', r.json.bundle)
  expect(c.code).toBe(2)
  expect(c.json.summary).toContain('changed after the harvest')
})

// ---------------------------------------------------------------- curate

t('curate drops weak, duplicate and rejected candidates, keeps an EDIT near its own target, and caps the rest', () => {
  const { home, work, repo, bundle } = curateRepo()
  put(home, `${R}/dreams/${bundle}/candidates.json`, JSON.stringify(ratchetCandidates('candidates.curate.json', repo)))
  const c = dream(work, 'curate', bundle)
  expect(c.code).toBe(0)
  expect(c.json).toMatchObject({ verdict: 'pass', items: 3, candidates: 7, dropped: { weak: 1, duplicate: 1, rejected: 1, cap: 1 } })

  const p = json(home, c.json.proposal)
  expect(p.items.map((i: any) => [i.id, i.op, i.entry, i.newId])).toEqual(
    [['P1', 'ADD', null, 'L-005'], ['P2', 'EDIT', 'L-001', null], ['P3', 'ADD', null, 'L-006']])
  // The ref `cp5/4-human.md:3` names no plan; it still finds the file, and a human file counts.
  expect(p.items[0]).toMatchObject({
    target: 'ratchet', repo, recurrence: 3, strong: true,
    evidence: ['demo/cp5/4-human.md:3', 'demo/cp1/3-triage-r1.json#cp1-A1-1', 'demo/cp2/3-triage-r1.json#cp2-A1-1'],
  })
  expect(p.items[1].rule).toContain('small screen')

  const md = read(home, `${R}/dreams/${bundle}/proposal.md`)
  expect(md.split('\n')[0]).toBe(`Dream ${bundle}: 3 proposals`)
  expect(md).toContain(`1. ADD ratchet in ${basename(repo)} L-005 (mobile/**/*.kt): Dismiss the keyboard`)
  expect(md).toContain(`2. EDIT ratchet in ${basename(repo)} L-001 (mobile/**)`)
  expect(md.trimEnd().split('\n').length).toBeLessThanOrEqual(2 + 3 * 3)

  const why = read(home, c.json.evidence)
  expect(why).toContain('drop weak ADD: one row and no human evidence')
  expect(why).toContain('drop duplicate ADD: near-duplicate of L-002')
  expect(why).toContain('drop rejected ADD: matches an item that the human rejected on 2026-10-03')
  expect(why).toContain('drop cap ADD: over the limit of 3 items')
  expect(json(home, `${R}/dreams/last.json`)).toMatchObject({ bundle, items: 3 })
  expect(json(home, `${R}/dreams/pending.json`)).toEqual({ bundles: [{ bundle, items: 3 }] })
})

t('curate checks the shape of each candidate, counts rows from the cites, and settles conflicts', () => {
  const { home, work, repo, bundle } = curateRepo({ maxItems: 10 })
  // The claimed counts are noise. The RETIRE says 9 rows, but each candidate cites one human file, so each counts one.
  const base = { target: 'ratchet', repo, scope: 'mobile/**', check: 'A test checks it.', evidence: ['cp5/4-human.md:4'] }
  const words = Array.from({ length: 41 }, (_, i) => `word${i}`).join(' ')
  const candidates = [
    { ...base, op: 'ADD', rule: 'Show the reconnecting banner when the socket drops.' },
    { ...base, op: 'ADD', rule: 'A rule without a check.', check: '' },
    { ...base, op: 'ADD', rule: words },
    { ...base, op: 'ADD', rule: 'A rule with a bad glob.', scope: 'src/**/*.{kt,swift}' },
    { ...base, op: 'RETIRE', id: 'L-099', rule: 'The target does not exist.' },
    { ...base, op: 'EDIT', id: 'L-002', rule: 'Log the request ID and the user on each error path.', check: 'Each catch block logs both.' },
    { ...base, op: 'RETIRE', id: 'L-002', rule: 'No finding cited it in 9 rows.', rows: 9 },
    { ...base, op: 'MERGE', id: ['L-003', 'L-004'], scope: 'mobile/**/*.kt, docs/**',
      rule: 'Keep the screen on a disconnect, and write one verb for each requirement.' },
    { ...base, op: 'MERGE', id: 'L-001, L-003', rule: 'Check fields and keep the screen on a disconnect.' },
    { ...base, op: 'ADD', rule: `Never log ${'pass' + 'word=' + 'hunter2'}.` },
    { ...base, op: 'ADD', rule: 'Keep status: retired out of a rule.' },
    { ...base, op: 'FOO', rule: 'An op that does not exist.' },
    { ...base, op: 'ADD', rule: 'A rule whose evidence is missing.', evidence: ['nope/4-human.md:1'] },
  ]
  put(home, `${R}/dreams/${bundle}/candidates.json`, JSON.stringify({ candidates }))
  const c = dream(work, 'curate', bundle)
  expect(c.code).toBe(0)
  expect(c.json.dropped).toEqual({ invalid: 7, evidence: 1, conflict: 2 })

  const p = json(home, c.json.proposal)
  // All survivors count one row with human evidence, so the order of the candidates settles each tie. The EDIT
  // comes before the RETIRE and wins L-002. The first MERGE wins L-003.
  expect(p.items.map((i: any) => [i.id, i.op, i.entry])).toEqual(
    [['P1', 'ADD', null], ['P2', 'EDIT', 'L-002'], ['P3', 'MERGE', ['L-003', 'L-004']]])
  expect(p.items[0]).toMatchObject({ recurrence: 1, strong: true, reason: '1 row, human evidence' })
  const why = read(home, c.json.evidence)
  expect(why).toContain('the rule has 41 words; the limit is 40')
  expect(why).toContain('braces are not supported')
  expect(why).toContain('entry L-099 not found')
  expect(why).toContain('the rule holds a secret')
  expect(why).toContain('L-002 is also changed by a better candidate')
})

t('curate treats a ref that two plans share as one file that exists, and never as two rows', () => {
  const { home, work } = makeHome()
  const repo = makeRepo(home)
  seed(home, repo)
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  for (const slug of ['a', 'b']) {
    copy(repo, 'human-cp5.md', `${EV}/${slug}/cp5/4-human.md`)
    triage(repo, slug, 'cp5', [finding('cp5-A1-1', 'Hidden field', { rule: 'L-001' })])
  }
  const h = dream(work, 'harvest')
  const base = { op: 'ADD', target: 'ratchet', repo, scope: 'mobile/**', check: 'A test checks it.', counter: [] }
  put(home, `${R}/dreams/${h.json.bundle}/candidates.json`, JSON.stringify({
    candidates: [
      // The second ref could be a/cp5 or b/cp5. Counting it as a row of its own would pass the two-row gate.
      { ...base, rule: 'Pin each feature flag default in a test.', evidence: ['b/cp5/3-triage-r1.json', 'cp5/3-triage-r1.json'] },
      // Both human files match, so the ref is human, but it names no row.
      { ...base, rule: 'Show the reconnecting banner when the socket drops.', evidence: ['cp5/4-human.md:4'] },
    ],
  }))
  const c = dream(work, 'curate', h.json.bundle)
  expect(c.json).toMatchObject({ verdict: 'pass', items: 1, dropped: { weak: 1 } })
  const p = json(home, c.json.proposal)
  expect(p.items[0]).toMatchObject({ recurrence: 0, strong: true, evidence: ['cp5/4-human.md:4'] })
})

t('curate takes the JSON from reflect.log when the reflection could not write candidates.json', () => {
  const { home, work, repo, bundle } = curateRepo()
  const dir = `${R}/dreams/${bundle}`
  const none = dream(work, 'curate', bundle)
  expect(none.code).toBe(2)
  expect(none.json.summary).toContain('gave no JSON answer')

  const answer = {
    candidates: [{
      op: 'ADD', target: 'ratchet', repo, scope: 'mobile/**', rule: 'Show the reconnecting banner when the socket drops.',
      check: 'A test drops the socket and expects the banner.', evidence: ['cp5/4-human.md:4'], counter: [],
    }],
  }
  put(home, `${dir}/reflect.log`, `I read the harvest.\n\`\`\`json\n${JSON.stringify(answer, null, 2)}\n\`\`\`\nA stray {brace}.\n`)
  const c = dream(work, 'curate', bundle)
  expect(c.code).toBe(0)
  expect(c.json).toMatchObject({ verdict: 'pass', items: 1 })
  expect(json(home, `${dir}/candidates.json`)).toEqual(answer)
  expect(read(home, c.json.evidence)).toContain("answer in reflect.log")
})

t('curate drops a fake cite, ignores a claimed count, and gates a global and a project rule by the cited turns', () => {
  const { home, work } = makeHome()
  session(home, '-tmp-demo', AAA, 'human.jsonl')
  session(home, '-tmp-demo', BBB, 'teammate-break.jsonl')
  session(home, '-tmp-demo', FFF, 'teammate-spec.jsonl')
  put(home, `${R}/dream.json`, JSON.stringify({ maxItems: 10 }))
  const h = dream(work, 'harvest', '--since', '2026-09-30')
  const words41 = Array.from({ length: 41 }, (_, i) => `word${i}`).join(' ')
  const g = (rule: string, evidence: string[], extra: Record<string, unknown> = {}) =>
    ({ op: 'ADD', target: 'global', rule, why: 'The human said so.', evidence, ...extra })
  const p = (rule: string, evidence: string[], extra: Record<string, unknown> = {}) =>
    ({ op: 'ADD', target: 'project', project: '-tmp-demo', rule, why: 'The human said so.', evidence, ...extra })
  const candidates = [
    // kept: the cited turn says "Always", and the counts that the model claims mean nothing
    g('Run the formatter before every commit.', ['aaaaaaaa#2'], { count: 99, rows: 9, recurrence: 9 }),
    // weak: one chore turn, and two turns of one session
    g('Check the harness before a retry.', ['aaaaaaaa#6'], { count: 99, rows: 9 }),
    g('Keep each chore in a script.', ['aaaaaaaa#6', 'aaaaaaaa#14']),
    // kept: two friction groups from two sessions (F1 review-break harness, F2 spec harness)
    g('Read each file before you edit it.', ['F1', 'F2']),
    g('A rule with a fake cite.', ['deadbeef#7']),
    // kept: a turn after an interrupt, which corrects the agent
    p('Stop and ask before you delete a build folder.', ['aaaaaaaa#11']),
    // weak: one turn with no tag
    p('Name the slash command in the reply.', ['aaaaaaaa#15']),
    p('A rule for a project that has no turn.', ['aaaaaaaa#2'], { project: '-tmp-nope' }),
    { ...p('Edit a memory.', ['aaaaaaaa#11']), op: 'EDIT', id: 'x' },
    { op: 'EDIT', target: 'global', id: 'G-099', rule: 'Edit a missing rule here.', why: 'x', evidence: ['aaaaaaaa#2'] },
    g('Scope a rule to files that exist.', ['aaaaaaaa#2'], { paths: ['/etc/**'] }),
    g('Scope a rule inside the project.', ['aaaaaaaa#2'], { paths: ['../x/**'] }),
    g(words41, ['aaaaaaaa#2']),
    g(`Never log ${'pass' + 'word=' + 'hunter2'}.`, ['aaaaaaaa#2']),
  ]
  put(home, `${R}/dreams/${h.json.bundle}/candidates.json`, JSON.stringify({ candidates }))
  const c = dream(work, 'curate', h.json.bundle)
  expect(c.code).toBe(0)
  expect(c.json).toMatchObject({ items: 3, candidates: 14, dropped: { invalid: 7, evidence: 1, weak: 3 } })

  const items = json(home, c.json.proposal).items
  // The friction cite spans two sessions, so it ranks first. The other two count one cited turn each.
  expect(items.map((i: any) => [i.target, i.rule.slice(0, 12), i.recurrence, i.strong, i.evidence])).toEqual([
    ['global', 'Read each fi', 2, false, ['F1', 'F2']],
    ['global', 'Run the form', 1, true, ['aaaaaaaa#2']],
    ['project', 'Stop and ask', 1, true, ['aaaaaaaa#11']],
  ])
  expect(items.map((i: any) => i.newId)).toEqual(['G-001', 'G-002', 'stop-and-ask-before-you-delete'])
  const why = read(home, c.json.evidence)
  for (const line of [
    'drop weak ADD: 1 session and no turn tagged rule - Check the harness',
    'drop weak ADD: 1 turn in that project and none is tagged',
    "project '-tmp-nope' has no human turn in this harvest",
    'a project memory supports ADD only',
    'rule G-099 not found among the active global rules',
    'bad path glob',
    'the rule has 41 words',
    'the rule holds a secret',
    'no evidence found: deadbeef#7',
  ]) {
    expect(why).toContain(line)
  }
  const md = read(home, `${R}/dreams/${h.json.bundle}/proposal.md`)
  expect(md).toContain('1. ADD global G-001: Read each file before you edit it.')
  expect(md).toContain('   Evidence: 2 sessions: F1, F2')
  expect(md).toContain('3. ADD memory of -tmp-demo stop-and-ask-before-you-delete: Stop and ask')
})

t('curate caps the global rules: an ADD needs room, and a RETIRE makes room', () => {
  const { home, work } = makeHome()
  session(home, '-tmp-demo', AAA, 'human.jsonl')
  put(home, `${R}/dream.json`, JSON.stringify({ globalCap: 2, maxItems: 5 }))
  for (const id of ['G-001', 'G-002']) {
    put(home, `.claude/rules/dream/${id}-rule.md`, `---\ndream-id: ${id}\nsource: 2026-10-01\nadded: 2026-10-01\n---\nKeep rule ${id} unique and short.\n\nWhy: a test\n`)
  }
  const add = { op: 'ADD', target: 'global', rule: 'Run the formatter before every commit.', why: 'The human said so.', evidence: ['aaaaaaaa#2'] }
  const retire = { op: 'RETIRE', target: 'global', id: 'G-001', why: 'It no longer holds.', evidence: ['aaaaaaaa#2'] }

  const h1 = dream(work, 'harvest', '--since', '2026-09-30')
  put(home, `${R}/dreams/${h1.json.bundle}/candidates.json`, JSON.stringify({ candidates: [add] }))
  const c1 = dream(work, 'curate', h1.json.bundle)
  expect(c1.json).toMatchObject({ items: 0, dropped: { cap: 1 } })
  expect(read(home, c1.json.evidence)).toContain('capped at 2, and 2 are active')

  const h2 = dream(work, 'harvest', '--since', '2026-09-30')
  expect(h2.json.bundle).not.toBe(h1.json.bundle)
  put(home, `${R}/dreams/${h2.json.bundle}/candidates.json`, JSON.stringify({ candidates: [add, retire] }))
  const c2 = dream(work, 'curate', h2.json.bundle)
  expect(c2.json).toMatchObject({ items: 2 })
  expect(json(home, c2.json.proposal).items.map((i: any) => [i.op, i.entry, i.newId])).toEqual([['ADD', null, 'G-003'], ['RETIRE', 'G-001', null]])
})

t('a candidate that the item cap cut is carried to the next dream, applies against its own harvest, and expires after 3 dreams', () => {
  const { home, work } = makeHome()
  session(home, '-tmp-demo', AAA, 'human.jsonl')
  put(home, `${R}/dream.json`, JSON.stringify({ maxItems: 1 }))
  const global = { op: 'ADD', target: 'global', rule: 'Run the formatter before every commit.', why: 'The human said so.', evidence: ['aaaaaaaa#2'] }
  const project = { op: 'ADD', target: 'project', project: '-tmp-demo', rule: 'Stop and ask before you delete a build folder.',
    why: 'The human stopped a delete.', evidence: ['aaaaaaaa#11'] }

  // Dream 1: the cap keeps one item. The other one waits for the next dream.
  const h1 = dream(work, 'harvest', '--since', '2026-09-30')
  put(home, `${R}/dreams/${h1.json.bundle}/candidates.json`, JSON.stringify({ candidates: [global, project] }))
  const c1 = dream(work, 'curate', h1.json.bundle)
  expect(c1.json).toMatchObject({ items: 1, carried: 1, dropped: { cap: 1 } })
  const carried = json(home, `${R}/dreams/carried.json`)
  expect(carried.items.map((i: any) => [i.kind, i.rule.slice(0, 12), i.from, i.age])).toEqual([['project', 'Stop and ask', h1.json.bundle, 0]])
  expect(read(home, c1.json.evidence)).toContain('carry ADD project: over the limit of 1 items - Stop and ask')
  expect(dream(work, 'apply', h1.json.bundle, '--reject', 'P1', '--reason', 'not now').code).toBe(0)

  // Dream 2 sees only another project, and nothing new is proposed. The carried item comes back, and
  // apply checks its project against the harvest of dream 1, which listed it.
  writeSession(home, '-tmp-other', EEE, [
    humanRec(EEE, '2026-10-03T09:00:00.000Z', '/tmp/other', 'Always run the linter first.'),
    asstRec(EEE, '2026-10-03T09:01:00.000Z', '/tmp/other'),
  ])
  const h2 = dream(work, 'harvest', '--since', '2026-10-03')
  expect(Object.keys(json(home, `${R}/dreams/${h2.json.bundle}/harvest.json`).projects)).toEqual(['-tmp-other'])
  put(home, `${R}/dreams/${h2.json.bundle}/candidates.json`, JSON.stringify({ candidates: [] }))
  const c2 = dream(work, 'curate', h2.json.bundle)
  expect(c2.json).toMatchObject({ items: 1, carried: 0 })
  const back = json(home, c2.json.proposal).items[0]
  expect(back).toMatchObject({ target: 'project', project: '-tmp-demo', carried: { from: h1.json.bundle }, evidence: ['aaaaaaaa#11'] })
  expect(read(home, `${R}/dreams/${h2.json.bundle}/proposal.md`)).toContain(`Evidence: carried from ${h1.json.bundle}, 1 turn`)
  expect(json(home, `${R}/dreams/carried.json`).items).toEqual([])
  expect(dream(work, 'apply', h2.json.bundle, '--accept', 'P1').code).toBe(0)
  expect(has(home, `${PROJECTS}/-tmp-demo/memory/stop-and-ask-before-you-delete.md`)).toBe(true)

  // A carried item that waited 3 dreams expires.
  put(home, `${R}/dreams/carried.json`, JSON.stringify({ version: 1, items: [{ ...carried.items[0], rule: 'Keep the cache warm before a test run.', age: 3 }] }))
  const h3 = dream(work, 'harvest', '--since', '2026-10-03', '--all')
  put(home, `${R}/dreams/${h3.json.bundle}/candidates.json`, JSON.stringify({ candidates: [] }))
  const c3 = dream(work, 'curate', h3.json.bundle)
  expect(c3.json).toMatchObject({ items: 0, carried: 0 })
  expect(read(home, c3.json.evidence)).toContain('expire ADD project: carried for 3 dreams - Keep the cache warm')
})

// ---------------------------------------------------------------- apply

t('apply writes a global rule file with paths and a project memory file with its index line, and records a rejection', () => {
  const { home, work } = makeHome()
  session(home, '-tmp-demo', AAA, 'human.jsonl')
  put(home, `${PROJECTS}/-tmp-demo/memory/MEMORY.md`, '- [existing](existing.md) — an older note\n')
  const h = dream(work, 'harvest', '--since', '2026-09-30')
  const bundle = h.json.bundle as string
  put(home, `${R}/dreams/${bundle}/candidates.json`, JSON.stringify({ candidates: [
    { op: 'ADD', target: 'global', rule: 'Run the formatter before every commit.', why: 'The human asked for it in plain words.',
      paths: ['**/*.swift', '**/*.{kt,kts}'], evidence: ['aaaaaaaa#2'] },
    { op: 'ADD', target: 'project', project: '-tmp-demo', rule: 'Reinstall the app after each finished change.',
      why: 'The human repeats the request in the same words.', apply: 'After a change is finished, reinstall the app before you report.',
      evidence: ['aaaaaaaa#6', 'aaaaaaaa#14'] },
    { op: 'ADD', target: 'project', project: '-tmp-demo', rule: 'Stop and ask before you delete a build folder.',
      why: 'The human stopped a delete.', evidence: ['aaaaaaaa#11'] },
  ] }))
  const c = dream(work, 'curate', bundle)
  expect(c.json.items).toBe(3)
  expect(json(home, `${R}/dreams/pending.json`)).toEqual({ bundles: [{ bundle, items: 3 }] })
  const items = json(home, c.json.proposal).items
  const id = (pred: (i: any) => boolean) => items.find(pred).id
  const global = id((i: any) => i.target === 'global')
  const reinstall = id((i: any) => i.rule.startsWith('Reinstall'))
  const stop = id((i: any) => i.rule.startsWith('Stop and ask'))

  const undecided = dream(work, 'apply', bundle, '--accept', global)
  expect(undecided.code).toBe(2)
  expect(has(home, '.claude/rules/dream')).toBe(false)

  const ok = dream(work, 'apply', bundle, '--accept', `${global},${reinstall}`, '--reject', stop, '--reason', 'too vague')
  expect(ok.code).toBe(0)
  expect(ok.json).toMatchObject({ verdict: 'pass', rejected: [stop], skipped: [] })
  const today = new Date().toISOString().slice(0, 10)
  expect(read(home, '.claude/rules/dream/G-001-run-the-formatter-before-every-commit.md')).toBe(
    `---\npaths:\n  - "**/*.swift"\n  - "**/*.{kt,kts}"\ndream-id: G-001\nsource: ${bundle}\nadded: ${today}\n---\n`
    + 'Run the formatter before every commit.\n\nWhy: The human asked for it in plain words.\n')
  const slug = 'reinstall-the-app-after-each-finished'
  expect(read(home, `${PROJECTS}/-tmp-demo/memory/${slug}.md`)).toBe(
    `---\nname: ${slug}\ndescription: Reinstall the app after each finished change.\nmetadata:\n  type: feedback\n  origin: dream\n---\n\n`
    + 'Reinstall the app after each finished change.\n\n**Why:** The human repeats the request in the same words.\n'
    + '**How to apply:** After a change is finished, reinstall the app before you report.\n')
  expect(read(home, `${PROJECTS}/-tmp-demo/memory/MEMORY.md`)).toBe(
    `- [existing](existing.md) — an older note\n- [${slug}](${slug}.md) — Reinstall the app after each finished change.\n`)
  const rejected = read(home, `${R}/dreams/rejected.jsonl`).trim().split('\n').map(l => JSON.parse(l))
  expect(rejected).toHaveLength(1)
  expect(rejected[0]).toMatchObject({ bundle, op: 'ADD', target: 'project', rule: 'Stop and ask before you delete a build folder.', reason: 'too vague' })
  // The review closes the bundle, and the pending index goes away with its last proposal.
  const review = json(home, `${R}/dreams/${bundle}/review.json`)
  expect(review.accepted).toEqual(expect.arrayContaining([
    { id: global, op: 'ADD', target: 'global', entry: 'G-001' }, { id: reinstall, op: 'ADD', target: 'project', entry: slug }]))
  expect(review).toMatchObject({ rejected: [stop], reason: 'too vague' })
  expect(has(home, `${R}/dreams/pending.json`)).toBe(false)
  expect(dream(work, 'apply', bundle, '--accept', global).json.summary).toContain('reviewed already')
  expect(dream(work, 'state').json).toMatchObject({ state: 'recent', pending: 0, bundle: null })

  // EDIT keeps the paths when it gives none, and RETIRE moves the file out of the folder that claude loads.
  const rule = (over: Record<string, unknown>) => ({ id: 'P1', op: 'EDIT', target: 'global', entry: 'G-001', paths: null, ...over })
  proposal(home, '2026-10-06', [rule({ rule: 'Run the formatter and the linter before every commit.', why: 'The human added the linter.' })])
  expect(dream(work, 'apply', '2026-10-06', '--accept', 'P1').code).toBe(0)
  const edited = read(home, '.claude/rules/dream/G-001-run-the-formatter-before-every-commit.md')
  expect(edited).toBe(`---\npaths:\n  - "**/*.swift"\n  - "**/*.{kt,kts}"\ndream-id: G-001\nsource: 2026-10-06\nadded: ${today}\nedited: ${today}\n---\n`
    + 'Run the formatter and the linter before every commit.\n\nWhy: The human added the linter.\n')
  proposal(home, '2026-10-07', [rule({ op: 'RETIRE', rule: '', why: 'The linter does it now.' })])
  expect(dream(work, 'apply', '2026-10-07', '--accept', 'P1').code).toBe(0)
  expect(has(home, '.claude/rules/dream/G-001-run-the-formatter-before-every-commit.md')).toBe(false)
  expect(has(home, `${R}/dreams/retired/G-001-run-the-formatter-before-every-commit.md`)).toBe(true)
  // A retired ID is never used again.
  proposal(home, '2026-10-08', [{ id: 'P1', op: 'ADD', target: 'global', rule: 'Keep every rule short.', why: 'Long rules get skipped.', paths: null }])
  expect(dream(work, 'apply', '2026-10-08', '--accept', 'P1').json.accepted).toEqual([{ id: 'P1', op: 'ADD', target: 'global', entry: 'G-002' }])
  // A project memory that exists already is skipped, and the index keeps one line.
  proposal(home, '2026-10-09', [{ id: 'P1', op: 'ADD', target: 'project', project: '-tmp-demo', newId: slug, rule: 'Reinstall the app after each finished change.', why: 'Again.' }])
  const again = dream(work, 'apply', '2026-10-09', '--accept', 'P1')
  expect(again.json).toMatchObject({ verdict: 'pass', accepted: [], skipped: [{ id: 'P1' }] })
  expect(read(home, `${PROJECTS}/-tmp-demo/memory/MEMORY.md`).match(new RegExp(`\\(${slug}\\.md\\)`, 'g'))).toHaveLength(1)
})

t('apply refuses a project or a repo that the harvest did not see, and one bad item changes nothing', () => {
  const { home, work } = makeHome()
  session(home, '-tmp-demo', AAA, 'human.jsonl')
  mkdirSync(join(home, PROJECTS, '-tmp-other'), { recursive: true })
  const h = dream(work, 'harvest', '--since', '2026-09-30')
  const bundle = h.json.bundle as string
  const good = { id: 'P1', op: 'ADD', target: 'global', rule: 'Run the formatter before every commit.', why: 'The human said so.' }
  const other = { id: 'P2', op: 'ADD', target: 'project', project: '-tmp-other', rule: 'A rule for a folder with no human turn.', why: 'None.' }
  proposal(home, bundle, [good, other])
  const r = dream(work, 'apply', bundle, '--accept', 'P1,P2')
  expect(r.code).toBe(2)
  expect(r.json.summary).toContain('has no human turn in this harvest')
  expect(has(home, '.claude/rules/dream')).toBe(false)
  expect(has(home, `${R}/dreams/${bundle}/review.json`)).toBe(false)

  const strange = { id: 'P2', op: 'ADD', target: 'project', project: '../escape', rule: 'A rule for a folder outside.', why: 'None.' }
  proposal(home, bundle, [good, strange])
  expect(dream(work, 'apply', bundle, '--accept', 'P1,P2').json.summary).toContain('bad project folder')
  const repo = makeRepo(home)
  proposal(home, bundle, [good, item(repo, 'P2')])
  expect(dream(work, 'apply', bundle, '--accept', 'P1,P2').json.summary).toContain('has no ratchet evidence in this harvest')
  expect(has(home, '.claude/rules/dream')).toBe(false)
})

t('apply ADD takes the next free ID, sets the origin, and keeps every other byte of learnings.md', () => {
  const { home, work } = makeHome()
  const repo = makeRepo(home)
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  const before = read(repo, `${R}/learnings.md`)
  proposal(home, BUNDLE, [item(repo, 'P1'), item(repo, 'P2', { rule: 'Second rule.' })])

  const undecided = dream(work, 'apply', BUNDLE, '--accept', 'P1')
  expect(undecided.code).toBe(2)
  expect(undecided.json.summary).toContain('P2')
  expect(read(repo, `${R}/learnings.md`)).toBe(before)

  const ok = dream(work, 'apply', BUNDLE, '--accept', 'P1', '--reject', 'P2', '--reason', 'too vague')
  expect(ok.code).toBe(0)
  expect(ok.json).toMatchObject({ verdict: 'pass', accepted: [{ id: 'P1', op: 'ADD', target: 'ratchet', entry: 'L-005' }], rejected: ['P2'] })
  const entry = '### L-005\n- scope: mobile/**/*.kt\n- rule: Dismiss the keyboard from every native text field.\n'
    + '- check: A UI test taps outside the field and expects no focus.\n'
    + '- source: demo/cp5/4-human.md:3, demo/cp1/3-triage-r1.json\n- origin: dream\n'
    + '- helpful: 0 · harmful: 0 · status: active\n'
  expect(read(repo, `${R}/learnings.md`)).toBe(`${before}\n${entry}`)
  // The real consumer finds the new entry by its scope.
  expect(sh(repo, ['bash', RS_SH, 'learnings', '--scope', 'mobile/app/Form.kt']).out).toContain('L-005')
  expect(json(home, `${R}/dreams/${BUNDLE}/review.json`)).toMatchObject({ accepted: [{ id: 'P1', entry: 'L-005' }], rejected: ['P2'] })

  const again = dream(work, 'apply', BUNDLE, '--accept', 'P1', '--reject', 'P2')
  expect(again.code).toBe(2)
  expect(again.json.summary).toContain('reviewed already')
  expect(read(repo, `${R}/learnings.md`).match(/### L-005/g)).toHaveLength(1)

  // A version 1 file keeps its bullets byte for byte. RS learnings ignores bullets outside entries, so apply warns.
  const old = makeRepo(home)
  copy(old, 'learnings.v1.md', `${R}/learnings.md`)
  proposal(home, '2026-10-06', [item(old, 'P1')])
  const v1 = dream(work, 'apply', '2026-10-06', '--accept', 'P1')
  expect(v1.json.warnings).toEqual(['3 bullet(s) of learnings.md sit outside any entry, and RS learnings ignores them'])
  expect(read(old, `${R}/learnings.md`).startsWith(readFileSync(join(FIX, 'learnings.v1.md'), 'utf8'))).toBe(true)
})

t('apply RETIRE, EDIT and MERGE change only the lines of their entries, and a rejection lands in rejected.jsonl', () => {
  const { home, work } = makeHome()
  const repo = makeRepo(home)
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  const before = read(repo, `${R}/learnings.md`)
  const items = [
    item(repo, 'P1', { op: 'RETIRE', entry: 'L-002', rule: 'No finding cited it.', scope: null, check: '' }),
    item(repo, 'P2', { op: 'EDIT', entry: 'L-001', scope: 'mobile/**, ios/**', rule: 'Check each text field with the keyboard open, on a device.', check: 'The device pack lists each text field.' }),
    item(repo, 'P3', { op: 'MERGE', entry: ['L-003', 'L-004'], scope: 'mobile/**/*.kt, docs/**', rule: 'Keep the screen on a disconnect, and write one verb for each requirement.', check: 'A test and the doc linter both pass.' }),
    item(repo, 'P4', { rule: 'Will be rejected.' }),
  ]

  // A bad answer changes nothing: an unknown ID, an ID in both lists, and an item whose entry is gone.
  proposal(home, '2026-10-04', [item(repo, 'P1'), item(repo, 'P2', { op: 'RETIRE', entry: 'L-099', rule: 'Gone.' })])
  expect(dream(work, 'apply', '2026-10-04', '--accept', 'P9', '--reject', 'P1,P2').code).toBe(2)
  expect(dream(work, 'apply', '2026-10-04', '--accept', 'P1', '--reject', 'P1,P2').code).toBe(2)
  expect(dream(work, 'apply', '2026-10-04', '--accept', 'P1,P2').code).toBe(2)
  expect(read(repo, `${R}/learnings.md`)).toBe(before)
  expect(has(home, `${R}/dreams/2026-10-04/review.json`)).toBe(false)

  proposal(home, BUNDLE, items)
  const r = dream(work, 'apply', BUNDLE, '--accept', 'P1,P2', '--accept', 'P3', '--reject', 'P4', '--reason', 'too vague')
  expect(r.code).toBe(0)
  expect(r.json.accepted).toEqual([
    { id: 'P1', op: 'RETIRE', target: 'ratchet', entry: 'L-002' }, { id: 'P2', op: 'EDIT', target: 'ratchet', entry: 'L-001' },
    { id: 'P3', op: 'MERGE', target: 'ratchet', entry: 'L-003' }])

  const expected = before
    .replace('status: active\n\n### L-003', 'status: retired\n\n### L-003')
    .replace('- scope: mobile/**\n- rule: Check each text field with the keyboard open, on a device or a simulator.\n- check: The device check pack lists each new text field.\n',
      '- scope: mobile/**, ios/**\n- rule: Check each text field with the keyboard open, on a device.\n- check: The device pack lists each text field.\n')
    .replace('- scope: mobile/**/*.kt\n- rule: Keep the screen on a transient disconnect and show a reconnecting banner.\n- check: A test drives a disconnect and expects the same screen.\n',
      '- scope: mobile/**/*.kt, docs/**\n- rule: Keep the screen on a disconnect, and write one verb for each requirement.\n- check: A test and the doc linter both pass.\n')
    .replace('status: active\n\n## Notes', `status: retired\n- note: merged into L-003 by dream ${BUNDLE}\n\n## Notes`)
  expect(read(repo, `${R}/learnings.md`)).toBe(expected)

  const rejected = read(home, `${R}/dreams/rejected.jsonl`).trim().split('\n').map(l => JSON.parse(l))
  expect(rejected).toHaveLength(1)
  expect(rejected[0]).toMatchObject({ bundle: BUNDLE, op: 'ADD', target: 'ratchet', rule: 'Will be rejected.', reason: 'too vague' })
  expect(rejected[0].date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  // The retired entry no longer reaches an agent, and the merged one does.
  const seen = sh(repo, ['bash', RS_SH, 'learnings', '--scope', 'server/x.ts', 'docs/a.md']).out
  expect(seen).not.toContain('L-002')
  expect(seen).not.toContain('L-004')
  expect(seen).toContain('L-003')
})

t('apply pins learnings.md again in each plan, and leaves every other pin and every stale pin alone', () => {
  const { home, work } = makeHome()
  const repo = makeRepo(home)
  copy(repo, 'learnings.v2.md', `${R}/learnings.md`)
  const state = `${EV}/demo/_state`
  put(repo, `${R}/list.txt`, `${R}/config.json\n${R}/learnings.md\n`)
  expect(sh(repo, ['bash', RS_SH, 'lock', state, '--from', `${R}/list.txt`]).code).toBe(0)
  const check = () => sh(repo, ['bash', RS_SH, 'check', state])
  expect(check().code).toBe(0)

  proposal(home, BUNDLE, [item(repo, 'P1')])
  const r = dream(work, 'apply', BUNDLE, '--accept', 'P1')
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
  proposal(home, '2026-10-06', [item(repo, 'P1', { rule: 'Another rule.' })])
  const stale = dream(work, 'apply', '2026-10-06', '--accept', 'P1')
  expect(stale.json).toMatchObject({ verdict: 'pass', relocked: 0, stalePins: [state] })
  const still = check()
  expect(still.code).toBe(1)
  expect(still.out).toContain('learnings.md')
})

// ---------------------------------------------------------------- install, state, nightly

t('install and state work outside a git repo, under RATCHET_HOME, and the repo list is gone', () => {
  const { home, work } = makeHome()
  const plist = join(home, 'Library', 'LaunchAgents', 'com.ratchet.dream.plist')
  expect(dream(work, 'state').json).toMatchObject({ state: 'due', pending: 0, bundle: null, budgetUsd: 2 })
  // The state check writes nothing when there is nothing to write.
  expect(has(home, R)).toBe(false)

  const i = dream(work, 'install')
  expect(i.code).toBe(0)
  expect(i.json).toMatchObject({ verdict: 'pass', loaded: false, configCreated: true })
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
  expect(json(home, `${R}/dream.json`)).toEqual({ nightly: true, maxItems: 3, budgetUsd: 2, sinceDays: 7, exclude: [], globalCap: 25 })
  expect(has(home, `${R}/repos.json`)).toBe(false)
  // A second install keeps the file that the human may have edited.
  put(home, `${R}/dream.json`, JSON.stringify({ nightly: false, budgetUsd: 0.5 }))
  expect(dream(work, 'install').json).toMatchObject({ configCreated: false })
  expect(dream(work, 'install').json.warnings.join(' ')).toContain('nightly is not true')
  expect(dream(work, 'state').json).toMatchObject({ state: 'off', budgetUsd: 0.5 })

  // recent: a dream under 20 hours ago. pending: a proposal that no review closed, and the oldest comes first.
  put(home, `${R}/dream.json`, JSON.stringify({}))
  put(home, `${R}/dreams/last.json`, JSON.stringify({ epoch: Date.now() / 1000 - 3600 }))
  expect(dream(work, 'state').json).toMatchObject({ state: 'recent', pending: 0 })
  put(home, `${R}/dreams/last.json`, JSON.stringify({ epoch: Date.now() / 1000 - 30 * 3600 }))
  expect(dream(work, 'state').json).toMatchObject({ state: 'due' })
  proposal(home, '2026-10-05', [item('/x', 'P1'), item('/x', 'P2')])
  proposal(home, '2026-10-03', [item('/x', 'P1')])
  expect(dream(work, 'state').json).toMatchObject({ state: 'pending', pending: 3, bundle: '2026-10-03' })
  expect(json(home, `${R}/dreams/pending.json`).bundles).toEqual([{ bundle: '2026-10-03', items: 1 }, { bundle: '2026-10-05', items: 2 }])

  for (const gone of ['register', 'repos']) expect(dream(work, gone).code).toBe(2)
  const u = dream(work, 'uninstall')
  expect(u.json).toMatchObject({ verdict: 'pass', removed: true, unloaded: false })
  expect(u.json.command).toContain('launchctl bootout gui/')
  expect(existsSync(plist)).toBe(false)
})

t('the nightly script harvests, runs a sealed claude from the bundle folder, curates, and then waits for the review', () => {
  const { home, work } = makeHome()
  // A git repo above the bundle: RS exec starts its command in the git top, so the script has to change folder itself.
  sh(home, ['git', 'init', '-q'])
  const sid = 'cccccccc-7777-4777-8777-777777777777'
  const ago = (s: number) => new Date(Date.now() - s * 1000).toISOString()
  writeSession(home, '-tmp-night', sid, [
    asstRec(sid, ago(120), '/tmp/night'),
    humanRec(sid, ago(60), '/tmp/night', 'Always run the formatter before you commit'),
  ])
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
  // The script runs from outside any repo, as launchd runs it.
  const run = () => sh(work, ['bash', NIGHTLY], env)
  const calls = () => readFileSync(`${claudeLog}.calls`, 'utf8').trim().split('\n').length

  const first = run()
  expect(first.code).toBe(0)
  const lines = first.out.trim().split('\n')
  expect(lines).toHaveLength(3)
  const bundle = readdirSync(join(home, R, 'dreams')).find(n => /^\d{4}-\d{2}-\d{2}$/.test(n))!
  expect(lines[0]).toContain(`harvested 1 new fact(s) into dream ${bundle}`)
  expect(lines[1]).toContain('reflecting with sonnet, budget 2 USD')
  expect(lines[2]).toContain(`proposed 1 item(s) in dream ${bundle}`)

  // The prompt comes first because --allowedTools takes a list. The run is sealed, and the model comes from reflect.md.
  expect(readFileSync(claudeLog, 'utf8').trim().split('\n')).toEqual(
    ['--model', 'sonnet', '--max-budget-usd', '2', '--safe-mode', '--restricted', '--no-session-persistence',
      '--allowedTools', 'Read'])
  // claude runs inside the bundle, which holds everything that the prompt names.
  expect(readFileSync(`${claudeLog}.pwd`, 'utf8').trim()).toBe(realpathSync(join(home, R, 'dreams', bundle)))
  const prompt = readFileSync(`${claudeLog}.prompt`, 'utf8')
  expect(prompt).toContain('You read what one person said to Claude Code')
  expect(prompt).toContain('Do not write a file. Your final answer is the candidates JSON')
  expect(prompt).not.toContain('model: sonnet')
  expect(has(home, `${R}/dreams/${bundle}/context/global-rules.md`)).toBe(true)

  const p = json(home, `${R}/dreams/${bundle}/proposal.json`)
  expect(p.items).toHaveLength(1)
  expect(p.items[0]).toMatchObject({ op: 'ADD', target: 'global', newId: 'G-001', strong: true, evidence: ['cccccccc#2'], paths: ['**/*.ts'] })
  // The dream proposes only. It never applies a change and never commits.
  expect(has(home, '.claude/rules')).toBe(false)
  expect(sh(home, ['git', 'rev-parse', '--verify', '-q', 'HEAD']).code).not.toBe(0)
  expect(dream(work, 'state').json).toMatchObject({ state: 'pending', pending: 1, bundle })

  const waiting = run()
  expect(waiting.out).toContain('skipped, a proposal waits for review')
  expect(calls()).toBe(1)

  expect(dream(work, 'apply', bundle, '--accept', 'P1').code).toBe(0)
  expect(has(home, '.claude/rules/dream/G-001-run-the-formatter-before-every-commit.md')).toBe(true)
  expect(run().out).toContain('skipped, the last dream is under 20 h old')

  // Off means off.
  put(home, `${R}/dream.json`, JSON.stringify({ nightly: false }))
  expect(run().out).toContain('skipped, nightly is off in dream.json')
  // A dream is due again after 20 hours, but the window starts at its marker: records older than that are no news.
  put(home, `${R}/dream.json`, JSON.stringify({ nightly: true }))
  put(home, `${R}/dreams/last.json`, JSON.stringify({ epoch: Date.now() / 1000 - 21 * 3600 }))
  writeSession(home, '-tmp-night', sid, [
    asstRec(sid, ago(23 * 3600), '/tmp/night'),
    humanRec(sid, ago(22 * 3600), '/tmp/night', 'Always run the formatter before you commit'),
  ])
  expect(run().out).toContain('nothing new')
  expect(calls()).toBe(1)
  // The budget can be a fraction of a dollar, and it comes from dream.json.
  put(home, `${R}/dream.json`, JSON.stringify({ budgetUsd: 0.5 }))
  writeSession(home, '-tmp-night', sid, [
    asstRec(sid, ago(120), '/tmp/night'),
    humanRec(sid, ago(60), '/tmp/night', 'Never push without asking me first'),
  ])
  const third = run()
  expect(third.out).toContain('budget 0.5 USD')
  expect(readFileSync(claudeLog, 'utf8').trim().split('\n').slice(0, 4)).toEqual(['--model', 'sonnet', '--max-budget-usd', '0.5'])
  expect(calls()).toBe(2)
})
