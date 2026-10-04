import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { DenActor, DenBeat, DenMode, DenPlan } from '../types'
import {
  clip,
  currentRow,
  gateLine,
  gateOf,
  iconOf,
  kTok,
  parsePlan,
  reconcile,
  roleOf,
  statusText,
  summarize,
  trackLine,
  verdictOf,
} from './logic'
import { compose, GONE_MS, pack, ROWS } from './scene'

const PANE = 'den'
const DOCK_COLUMNS = 48
const TICK_MS = 80 // hyper's frame period; calm draws every third tick
const HYPER_IDLE_MS = 90_000 // hyper relaxes after this long with no ratchet work
const PLAN_DIR = '.claude/ratchet/plans'

const actors = atom({ plugin: 'den', key: 'actors' } as const, [])
const mode = atom({ plugin: 'den', key: 'mode' } as const, 'calm')
const plan = atom({ plugin: 'den', key: 'plan' } as const, null)
const ticker = atom({ plugin: 'den', key: 'ticker' } as const, [])
const beats = atom({ plugin: 'den', key: 'beats' } as const, [])

// The module's own bookkeeping: a hot reload starts these over, which costs at
// most one redraw.
let mounted: { cols: number; rows: number } | undefined
let isOpen = false
let dismissed = false // the person closed the pane: nothing reopens it unasked
let lastCells = ''
let lastStatus: string | undefined = '∅'
let tickN = 0
let lastRatchetAt = 0
let lastPlanPoll = 0
let demoTimers: Timer[] = []
let demoPlanBefore: DenPlan | null = null

type $ = EngineInterface

const frameOf = (md: DenMode) => (md === 'calm' ? Math.floor(tickN / 3) : tickN)

async function say($: $, line: string) {
  const now = await $.clock.now()
  const hhmm = new Date(now).toTimeString().slice(0, 5)
  await update($, ticker, t => [...t, `${hhmm} ${line}`].slice(-12))
}

async function beat($: $, kind: DenBeat['kind']) {
  const at = await $.clock.now()
  await update($, beats, bs => [...bs.filter(b => b.kind !== kind), { kind, at }])
}

async function patch($: $, id: string, p: Partial<DenActor>) {
  await update($, actors, list => list.map(a => (a.id === id ? { ...a, ...p } : a)))
}

async function ensureMain($: $) {
  const list = await read($, actors)
  if (list.some(a => a.kind === 'main')) return
  const now = await $.clock.now()
  const main: DenActor = { id: 'main', kind: 'main', type: 'main', label: 'Claude', status: 'idle', activity: 'napping', bornAt: now }
  await update($, actors, l => [main, ...l.filter(a => a.id !== 'main')])
}

async function openPane($: $) {
  const md = await read($, mode)
  const r = await $.ui.open({
    id: PANE,
    title: md === 'hyper' ? '🦝 RATCHET' : '🦝 den',
    columns: DOCK_COLUMNS,
    rows: ROWS[md] + 12,
  })
  isOpen = r.isPlaced
  return r
}

async function autoOpen($: $) {
  if (isOpen || dismissed) return
  if ((await $.store.get('den.auto')) === false) return
  await openPane($)
}

async function setMode($: $, md: DenMode) {
  if ((await read($, mode)) === md) return
  await update($, mode, () => md)
  if (md === 'calm') await update($, actors, list => list.filter(a => !a.role || a.status === 'working'))
  if (isOpen) await openPane($) // carries the new title
}

async function goHyper($: $) {
  lastRatchetAt = await $.clock.now()
  if ((await read($, mode)) === 'hyper') return
  await setMode($, 'hyper')
  await say($, '⚡ RATCHET MODE — everybody up')
  if (!isOpen && !dismissed) await openPane($)
}

async function addAgent($: $, id: string, type: string, description: string) {
  const now = await $.clock.now()
  const role = roleOf(type)
  const agent: DenActor = {
    id,
    kind: 'agent',
    type,
    ...(role ? { role } : {}),
    label: role ?? type,
    status: 'working',
    activity: clip(description || 'starting…'),
    bornAt: now,
    seenAt: now,
  }
  // One raccoon per ratchet role: a fresh spawn takes over the finished one's station.
  await update($, actors, list => [
    ...list.filter(a => a.id !== id && !(role && a.role === role && a.status !== 'working')),
    agent,
  ])
  if (role) await goHyper($)
  else await autoOpen($)
  await say($, `${iconOf(agent)} ${agent.label} ${role ? 'on it' : 'climbs out'}: ${clip(description, 28)}`)
}

/** A subagent's tool call: its activity; an agent we never saw spawn is looked up. */
async function touchAgent($: $, id: string, p: Partial<DenActor>) {
  if (!(await read($, actors)).some(a => a.id === id)) {
    const info = (await $.agent.list()).find(x => x.id === id)
    if (!info) return // a workflow's or the engine's own loop: not ours to draw
    await addAgent($, id, info.type, info.description)
  }
  const now = await $.clock.now()
  await update($, actors, list =>
    list.map(a => {
      if (a.id !== id) return a
      const { endedAt: _gone, ...rest } = a
      return { ...rest, ...p, status: 'working' as const, seenAt: now }
    }),
  )
}

async function finishAgent(
  $: $,
  id: string,
  out: { answer: string; durationMs: number; failed: boolean; reason?: string; tokens?: number },
) {
  const a = (await read($, actors)).find(x => x.id === id)
  if (!a) return
  const now = await $.clock.now()
  const v = out.failed ? { verdict: 'fail' as const, note: out.reason ?? 'failed' } : verdictOf(a.role, out.answer)
  await patch($, id, {
    status: out.failed ? 'failed' : 'done',
    endedAt: now,
    ms: out.durationMs,
    ...(out.tokens !== undefined ? { tokens: out.tokens } : {}),
    tool: undefined,
    activity: v.note ?? 'done',
    ...(v.verdict ? { verdict: v.verdict } : {}),
  })
  const tok = out.tokens ? ` · ${kTok(out.tokens)} tok` : ''
  await say($, `${iconOf(a)} ${a.label}: ${v.note ?? 'done'} · ${Math.round(out.durationMs / 1000)}s${tok}`)
}

async function applyPlan($: $, next: DenPlan) {
  const prev = await read($, plan)
  if (prev && JSON.stringify(prev) === JSON.stringify(next)) return
  await update($, plan, () => next)
  if (!prev || prev.slug !== next.slug) return // first sight of this plan: no fanfare
  const was = new Set(prev.rows.filter(r => r.status === 'approved').map(r => r.id))
  const locked = next.rows.filter(r => r.status === 'approved' && !was.has(r.id))
  if (!locked.length) return
  const done = next.rows.filter(r => r.status === 'approved').length
  await beat($, 'click')
  for (const r of locked) {
    $.ui.toast(`⚙ ${r.id} locked (${done}/${next.rows.length})`)
    await say($, `⚙ CLICK — ${r.id} locked: ${clip(r.title, 26)}`)
  }
  if (done === next.rows.length) {
    await beat($, 'confetti')
    await say($, '🎉 plan done — every checkpoint locked')
  }
}

async function refreshPlan($: $) {
  if (demoTimers.length) return // the demo owns the plan while it plays
  if (!(await $.fs.exists(PLAN_DIR))) return
  const files = (await $.fs.list(PLAN_DIR)).filter(
    f => f.kind === 'file' && f.name.endsWith('.md') && !f.name.endsWith('.reference.md'),
  )
  const newest = [...files].sort((a, b) => b.mtimeMs - a.mtimeMs)[0]
  if (!newest) return
  const rows = parsePlan(await $.fs.read(`${PLAN_DIR}/${newest.name}`))
  if (rows.length) await applyPlan($, { slug: newest.name.replace(/\.md$/, ''), rows })
}

/** The helper script's mechanics, read back as beats. */
async function ratchetBash($: $, cmd: string, out: string) {
  const snap = /snap\s+[\w.-]+\/(cp\d+)\/(base|gated)\b/.exec(cmd)
  if (/\scheck\s/.test(cmd) && /CHANGED|VANISHED/.test(out)) {
    await beat($, 'tamper')
    await say($, '🚨 TAMPERING CAUGHT — spec restored')
  } else if (snap?.[2] === 'gated') await say($, `✅ ${snap[1]} through gates 1–3`)
  else if (snap?.[2] === 'base') await say($, `▶ ${snap[1]} — here we go`)
  else if (/\sstage\s/.test(cmd)) await say($, '📦 staging the checkpoint')
  else if (/\stripwire\s/.test(cmd) && out && !out.includes('tripwire: clean')) await say($, '🪤 tripwire hit')
  await goHyper($)
}

async function housekeeping($: $, now: number, md: DenMode) {
  // The demo's actors aren't the engine's: leave them to its timeline.
  if (!demoTimers.length) {
    const before = await read($, actors)
    const after = reconcile(before, await $.agent.list(), now)
    if (after !== before) await update($, actors, () => [...after])
  }
  const list = await read($, actors)
  const keep = list.filter(
    a => a.kind === 'main' || a.role || a.status === 'working' || a.endedAt === undefined || now - a.endedAt < GONE_MS,
  )
  if (keep.length !== list.length) await update($, actors, () => keep)
  const bs = await read($, beats)
  const live = bs.filter(b => b.kind === 'waiting' || now - b.at < (b.kind === 'confetti' ? 8000 : 4000))
  if (live.length !== bs.length) await update($, beats, () => live)

  if (md === 'hyper') {
    const party = bs.find(b => b.kind === 'confetti')
    const waiting = bs.some(b => b.kind === 'waiting')
    const crewBusy = list.some(a => a.role && a.status === 'working')
    if ((party && now - party.at > 10_000) || (!waiting && !crewBusy && now - lastRatchetAt > HYPER_IDLE_MS)) {
      await setMode($, 'calm')
      await say($, 'the den calms down')
    } else if (now - lastPlanPoll > 3000) {
      lastPlanPoll = now
      await refreshPlan($)
    }
  }
  const status = statusText(md, list, await read($, plan), mounted !== undefined)
  if (status !== lastStatus) {
    lastStatus = status
    $.ui.status(status)
  }
}

async function tick($: $) {
  tickN++
  if (!mounted && tickN % 12) return // hidden: only the once-a-second chores
  const md = await read($, mode)
  if (md === 'calm' && tickN % 3) return
  const now = await $.clock.now()
  if (tickN % 12 === 0) await housekeeping($, now, md)
  if (!mounted || mounted.rows !== ROWS[md]) return // a mode switch redraws the pane first
  const frame = compose({ mode: md, actors: await read($, actors), beats: await read($, beats), now }, mounted.cols, frameOf(md))
  const cells = pack(frame)
  if (cells === lastCells) return
  lastCells = cells
  const r = await $.ui.blit({ requestId: PANE, key: 'scene', cells })
  if (r && 'deny' in r && r.deny) mounted = undefined
}

// ── /den demo: ~55 s of raccoon work, calm first, then a ratchet frenzy ──────
async function runDemo($: $) {
  for (const t of demoTimers) t.cancel()
  demoTimers = []
  demoPlanBefore = await read($, plan)
  const at = (ms: number, fn: () => Promise<unknown>) => {
    demoTimers.push($.clock.after(ms, () => void fn()))
  }
  const rows = (s: [string, string][]) => s.map(([id, status], i) => ({ id, title: ['skeleton', 'header', 'list rows', 'error states'][i]!, status }))
  const verdict = (v: string, n = 0) =>
    JSON.stringify({ verdict: v, findings: Array.from({ length: n }, (_, i) => ({ id: `F${i}`, severity: 'high', issue: '"" input crashes slugify' })) })

  await ensureMain($)
  at(0, () => patch($, 'main', { status: 'working', tool: undefined, activity: 'thinking…' }))
  at(1800, () => patch($, 'main', { tool: 'Read', activity: 'Read src/app.ts' }))
  at(3500, () => addAgent($, 'demo-x', 'Explore', 'find the auth flow'))
  at(4300, () => addAgent($, 'demo-g', 'general-purpose', 'run the test suite'))
  at(5200, () => patch($, 'main', { tool: 'Edit', activity: 'Edit src/app.ts' }))
  at(6500, () => touchAgent($, 'demo-x', { tool: 'Grep', activity: 'grep useAuth' }))
  at(7500, () => touchAgent($, 'demo-g', { tool: 'Bash', activity: '$ bun test' }))
  at(10_000, () => finishAgent($, 'demo-x', { answer: 'found it', durationMs: 6500, failed: false, tokens: 18_400 }))
  at(12_000, () => finishAgent($, 'demo-g', { answer: 'green', durationMs: 7700, failed: false, tokens: 9100 }))
  at(13_500, () => patch($, 'main', { tool: 'Skill', activity: '/ratchet run --auto' }))
  at(14_500, async () => {
    await update($, plan, () => ({ slug: 'demo', rows: rows([['cp1', 'approved'], ['cp2', 'todo'], ['cp3', 'todo'], ['cp4', 'todo']]) }))
    await goHyper($)
  })
  at(15_500, () => addAgent($, 'demo-spec', 'ratchet:spec', 'cp2 header: write the spec'))
  at(19_000, async () => {
    await finishAgent($, 'demo-spec', { answer: 'cases:\n- renders title\n- shows avatar\n- truncates long names\nred: …', durationMs: 3500, failed: false, tokens: 21_000 })
    await applyPlan($, { slug: 'demo', rows: rows([['cp1', 'approved'], ['cp2', 'red'], ['cp3', 'todo'], ['cp4', 'todo']]) })
  })
  at(19_800, () => addAgent($, 'demo-impl', 'ratchet:implement', 'cp2: make the spec pass'))
  at(21_000, () => touchAgent($, 'demo-impl', { tool: 'Edit', activity: 'Edit src/Header.tsx' }))
  at(23_500, () => ratchetBash($, 'bash ratchet.sh check .claude/ratchet/evidence/demo/*', 'CHANGED  src/Header.test.tsx'))
  at(25_000, () => finishAgent($, 'demo-impl', { answer: '', durationMs: 5200, failed: false, tokens: 64_000 }))
  at(25_500, () => addAgent($, 'demo-vis', 'ratchet:visual', 'cp2: compare captures'))
  at(26_000, () => addAgent($, 'demo-arch', 'ratchet:review-arch', 'cp2: conformance review'))
  at(26_300, () => addAgent($, 'demo-break', 'ratchet:review-break', 'cp2: break it'))
  at(29_000, () => finishAgent($, 'demo-vis', { answer: verdict('PASS'), durationMs: 3500, failed: false, tokens: 12_000 }))
  at(31_000, () => finishAgent($, 'demo-arch', { answer: verdict('APPROVE'), durationMs: 5000, failed: false, tokens: 30_000 }))
  at(32_000, () => finishAgent($, 'demo-break', { answer: verdict('CHANGES', 2), durationMs: 5700, failed: false, tokens: 51_000 }))
  at(33_000, () => addAgent($, 'demo-impl2', 'ratchet:implement', 'cp2: fix B1, B2'))
  at(36_000, () => finishAgent($, 'demo-impl2', { answer: '', durationMs: 3000, failed: false, tokens: 22_000 }))
  at(36_500, () => addAgent($, 'demo-break2', 'ratchet:review-break', 'cp2: re-check the delta'))
  at(39_500, async () => {
    await finishAgent($, 'demo-break2', { answer: verdict('APPROVE'), durationMs: 3000, failed: false, tokens: 15_000 })
    await applyPlan($, { slug: 'demo', rows: rows([['cp1', 'approved'], ['cp2', 'green'], ['cp3', 'todo'], ['cp4', 'todo']]) })
    await patch($, 'main', { status: 'idle', tool: undefined, activity: 'waiting on you' })
    await beat($, 'waiting')
    await say($, '✋ cp2 waits for you (B4)')
  })
  at(45_500, async () => {
    await update($, beats, bs => bs.filter(b => b.kind !== 'waiting'))
    await applyPlan($, { slug: 'demo', rows: rows([['cp1', 'approved'], ['cp2', 'approved'], ['cp3', 'todo'], ['cp4', 'todo']]) })
  })
  at(48_500, () => applyPlan($, { slug: 'demo', rows: rows([['cp1', 'approved'], ['cp2', 'approved'], ['cp3', 'approved'], ['cp4', 'todo']]) }))
  at(50_500, () => applyPlan($, { slug: 'demo', rows: rows([['cp1', 'approved'], ['cp2', 'approved'], ['cp3', 'approved'], ['cp4', 'approved']]) }))
  at(58_000, async () => {
    await update($, actors, list => list.filter(a => !a.id.startsWith('demo-')))
    await update($, plan, () => demoPlanBefore)
    await setMode($, 'calm')
    await patch($, 'main', { status: 'idle', tool: undefined, activity: 'napping' })
    demoTimers = []
    await say($, 'demo over — back to the real den')
  })
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'den',
      description: 'Raccoons at work: toggle the den pane (demo · auto on|off · calm · hyper)',
      argumentHint: '[demo | auto on|off | calm | hyper]',
    })
    lastRatchetAt = await $.clock.now()
    await ensureMain($)
    await refreshPlan($)
    $.clock.every(TICK_MS, () => void tick($))
    return next(e)
  })

  on('command.run', { command: 'den' }, async ($, e) => {
    const arg = e.args.trim().toLowerCase()
    dismissed = false
    if (arg === 'demo') {
      await runDemo($)
      const r = await openPane($)
      return { text: r.isPlaced ? '🦝 den demo: about a minute of raccoon work.' : `🦝 den demo running; pane not placed: ${r.reason}` }
    }
    const auto = /^auto\s+(on|off)$/.exec(arg)
    if (auto) {
      await $.store.set('den.auto', auto[1] === 'on')
      return { text: `🦝 den auto-open ${auto[1]}.` }
    }
    if (arg === 'calm' || arg === 'hyper') {
      if (arg === 'hyper') lastRatchetAt = await $.clock.now()
      await setMode($, arg)
      await openPane($)
      return { text: `🦝 den: ${arg}.` }
    }
    if (isOpen) {
      await $.ui.close({ id: PANE })
      isOpen = false
      return { text: '🦝 den closed.' }
    }
    const r = await openPane($)
    return { text: r.isPlaced ? '🦝 den opened.' : `🦝 den: ${r.reason}` }
  })

  on('ui.close', async ($, e, next) => {
    if (e.id === PANE) {
      isOpen = false
      mounted = undefined
      if (e.origin.kind === 'person') dismissed = true
    }
    return next(e)
  })

  on('skill.prompt', async ($, e, next) => {
    if (/(^|:)ratchet$/.test(e.skill)) await goHyper($)
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    await ensureMain($)
    await patch($, 'main', { status: 'working', tool: undefined, activity: 'thinking…' })
    await update($, beats, bs => bs.filter(b => b.kind !== 'waiting'))
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    if (e.agentId) {
      const u = e.usage as Record<string, unknown> | undefined
      const tokens = u
        ? ['input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens']
            .map(k => (typeof u[k] === 'number' ? (u[k] as number) : 0))
            .reduce((s, n) => s + n, 0)
        : undefined
      await finishAgent($, e.agentId, {
        answer: e.answer,
        durationMs: e.durationMs,
        failed: e.reason !== 'answer',
        reason: e.reason,
        ...(tokens !== undefined ? { tokens } : {}),
      })
      return r
    }
    await patch($, 'main', { status: 'idle', tool: undefined, activity: 'napping' })
    if ((await read($, mode)) === 'hyper') {
      const busy = (await read($, actors)).some(a => a.kind === 'agent' && a.status === 'working')
      const pl = await read($, plan)
      const allDone = !!pl && pl.rows.length > 0 && pl.rows.every(x => x.status === 'approved')
      if (!busy && !allDone) await beat($, 'waiting')
    }
    return r
  })

  on('agent.spawn', async ($, e, next) => {
    const r = await next(e)
    if ('agentId' in r && r.agentId) await addAgent($, r.agentId, e.subagentType || 'general-purpose', e.description ?? '')
    return r
  })

  on('tool.call', async ($, e, next) => {
    const input = e as unknown as Record<string, unknown>
    const activity = summarize(e.tool, input)
    if (e.agentId) await touchAgent($, e.agentId, { tool: e.tool, activity })
    else {
      await ensureMain($)
      await patch($, 'main', { status: 'working', tool: e.tool, activity })
    }
    const r = await next(e)
    if (e.agentId) return r
    await patch($, 'main', { tool: undefined, activity: 'thinking…' })
    const cmd = typeof input.command === 'string' ? input.command : ''
    if (e.tool === 'Bash' && cmd.includes('ratchet.sh')) await ratchetBash($, cmd, 'text' in r ? (r.text ?? '') : '')
    const path = typeof input.file_path === 'string' ? input.file_path : ''
    if ((e.tool === 'Write' || e.tool === 'Edit') && path.includes('.claude/ratchet/plans/')) await refreshPlan($)
    return r
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const list = await read($, actors)
    const md = await read($, mode)
    const pl = await read($, plan)
    const lines = await read($, ticker)
    const bs = await read($, beats)
    const now = await $.clock.now()
    const cols = Math.max(24, Math.min(160, e.props.bodyColumns))
    const { Box, Text } = $.ui.resolve(e)
    const hyper = md === 'hyper'

    let scene
    if (e.surface === 'terminal') {
      const { Raster } = $.ui.resolve(e)
      const rows = ROWS[md]
      const cells = pack(compose({ mode: md, actors: list, beats: bs, now }, cols, frameOf(md)))
      mounted = { cols, rows }
      lastCells = cells
      scene = <Raster key="scene" columns={cols} rows={rows} cells={cells} />
    } else {
      scene = <Text>{list.map(a => (a.status === 'working' ? '🦝' : '💤')).join(' ')}</Text>
    }

    const working = list.filter(a => a.kind === 'agent' && a.status === 'working').length
    const row = currentRow(pl)
    const gate = gateOf(pl, list)
    const done = pl?.rows.filter(r => r.status === 'approved').length ?? 0
    const roster = [
      ...list.filter(a => a.kind === 'main'),
      ...list.filter(a => a.kind === 'agent' && a.status === 'working'),
      ...list.filter(a => a.kind === 'agent' && a.status !== 'working'),
    ].slice(0, hyper ? 7 : 5)
    const extra = list.filter(a => a.kind === 'agent').length - (roster.length - 1)

    return (
      <Box flexDirection="column">
        {hyper ? (
          <Text bold color="#ff8a1f" wrap="truncate-end">
            RATCHET{pl ? ` · ${pl.slug}` : ''}
            {row ? ` · ${row.id}` : ''}
            {gate ? ` ${gate}` : ''} ⚙ {done}/{pl?.rows.length ?? 0}
            {bs.some(b => b.kind === 'tamper') ? '  🚨' : ''}
          </Text>
        ) : (
          <Text bold wrap="truncate-end">
            den · {working ? `${working} at work` : list.find(a => a.kind === 'main')?.status === 'working' ? 'Claude at work' : 'all quiet'}
          </Text>
        )}
        {scene}
        {hyper && pl ? <Text wrap="truncate-end">{trackLine(pl)}</Text> : null}
        {hyper ? <Text dimColor wrap="truncate-end">{gateLine(gate)}</Text> : null}
        {roster.map(a => (
          <Text
            key={`r-${a.id}`}
            wrap="truncate-end"
            dimColor={a.status !== 'working'}
            color={a.status === 'failed' || a.verdict === 'changes' ? '#e5484d' : a.verdict === 'approve' && a.status === 'done' ? '#43b581' : undefined}
          >
            {iconOf(a)} {a.label.padEnd(12).slice(0, 12)} {a.activity}
            {a.status === 'working' && a.kind === 'agent' ? ` · ${Math.round((now - a.bornAt) / 1000)}s` : ''}
            {a.tokens ? ` · ${kTok(a.tokens)} tok` : ''}
          </Text>
        ))}
        {extra > 0 ? <Text dimColor>+{extra} more</Text> : null}
        {lines.slice(hyper ? -5 : -3).map((l, i) => (
          <Text key={`t-${i}`} dimColor wrap="truncate-end">
            ▸ {l}
          </Text>
        ))}
      </Box>
    )
  })
}
