// What the den reads out of events: pure functions, so the tests cover them
// without an engine.
import type { DenActor, DenPlan, DenPlanRow, DenRole } from '../types'

const ROLE_NAMES: readonly string[] = ['spec', 'implement', 'visual', 'review-arch', 'review-break']

/** An agent with no tool call for this long is waiting, not working (an idle teammate). */
export const STALE_MS = 120_000

/** Ids of the actors drawn from the live file: ratchet agents the engine's list never shows. */
export const LIVE_PREFIX = 'live:'
const LIVE_MAX_AGE_MS = 6 * 60 * 60 * 1000 // a crashed run leaves `active: true` behind
const LIVE_ROLES = new Map<string, DenRole>([
  ['spec', 'spec'],
  ['implement', 'implement'],
  ['visual', 'visual'],
  ['arch', 'review-arch'],
  ['break', 'review-break'],
  ['review-arch', 'review-arch'],
  ['review-break', 'review-break'],
])

/**
 * Squares the den's working agents with the engine's list: an agent the engine
 * stopped, finished or lost (TaskStop fires no turn end) is done; one quiet past
 * STALE_MS is idle until its next tool call. Returns the actors, or the same
 * array when nothing changed.
 */
export function reconcile(
  actors: readonly DenActor[],
  engine: readonly { id: string; status: string }[],
  now: number,
): readonly DenActor[] {
  let changed = false
  const next = actors.map(a => {
    // The live file, not the engine's list, says whether a `live:` actor works.
    if (a.kind !== 'agent' || a.status !== 'working' || a.id.startsWith(LIVE_PREFIX)) return a
    const info = engine.find(x => x.id === a.id)
    if (info && info.status !== 'running') {
      changed = true
      const failed = info.status === 'failed'
      return { ...a, status: failed ? ('failed' as const) : ('done' as const), endedAt: now, tool: undefined, activity: info.status === 'killed' ? 'stopped' : failed ? 'failed' : 'done' }
    }
    if (now - (a.seenAt ?? a.bornAt) > STALE_MS) {
      changed = true
      return { ...a, status: 'idle' as const, tool: undefined, activity: 'waiting' }
    }
    return a
  })
  return changed ? next : actors
}

export type LiveRole = { role: DenRole; status: string; since?: number }
export type LiveRun = { cp?: string; gate?: string; round?: number; roles: LiveRole[] }

/** What `.claude/ratchet/live.json` says is running, or null when no run is (inactive, stale, missing or unreadable). */
export function parseLive(text: string, now: number): LiveRun | null {
  let live: Record<string, unknown> | null
  try {
    live = JSON.parse(text)
  } catch {
    return null
  }
  const at = typeof live?.updated === 'string' ? Date.parse(live.updated) : NaN
  if (live?.active !== true || !Number.isFinite(at) || now - at >= LIVE_MAX_AGE_MS) return null
  const roles: LiveRole[] = []
  for (const entry of Array.isArray(live.roles) ? (live.roles as Record<string, unknown>[]) : []) {
    const role = typeof entry?.role === 'string' ? LIVE_ROLES.get(entry.role) : undefined
    if (!role) continue
    const since = typeof entry.since === 'string' ? Date.parse(entry.since) : NaN
    roles.push({
      role,
      status: typeof entry.status === 'string' ? entry.status : '',
      ...(Number.isFinite(since) ? { since } : {}),
    })
  }
  return {
    ...(typeof live.cp === 'string' ? { cp: live.cp } : {}),
    ...(typeof live.gate === 'string' ? { gate: live.gate } : {}),
    ...(typeof live.round === 'number' ? { round: live.round } : {}),
    roles,
  }
}

function liveActor(prev: DenActor | undefined, r: LiveRole, live: LiveRun, now: number): DenActor {
  const status = r.status === 'working' ? 'working' : r.status === 'failed' ? 'failed' : r.status === 'done' ? 'done' : 'idle'
  const where = [live.cp, live.gate && (live.round ? `${live.gate} r${live.round}` : live.gate)].filter(Boolean).join(' ')
  return {
    id: `${LIVE_PREFIX}${r.role}`,
    kind: 'agent',
    type: `ratchet:${r.role}`,
    role: r.role,
    label: r.role,
    status,
    activity: status === 'working' ? where || 'working' : status === 'idle' ? 'waiting' : status,
    bornAt: r.since ?? (prev?.status === 'working' ? prev.bornAt : now),
    ...(status === 'done' || status === 'failed' ? { endedAt: prev?.endedAt ?? now } : {}),
  }
}

const sameLive = (a: DenActor, b: DenActor) =>
  a.status === b.status && a.activity === b.activity && a.bornAt === b.bornAt && a.endedAt === b.endedAt

/**
 * Squares the den with a live ratchet run: one `live:<role>` actor per role in the
 * live file, working while the file says so, done once the role leaves the list or
 * the run ends. Returns the actors, or the same array when nothing changed.
 */
export function syncLive(actors: readonly DenActor[], live: LiveRun | null, now: number): readonly DenActor[] {
  // A real agent working in a role already draws it.
  const real = new Set(actors.filter(a => a.status === 'working' && !a.id.startsWith(LIVE_PREFIX)).map(a => a.role))
  const want = new Map<DenRole, LiveRole>()
  for (const r of live?.roles ?? []) {
    const had = want.get(r.role)
    if (!real.has(r.role) && (!had || (had.status !== 'working' && r.status === 'working'))) want.set(r.role, r)
  }

  let changed = false
  const next: DenActor[] = []
  const placed = new Set<DenRole>()
  for (const a of actors) {
    if (!a.id.startsWith(LIVE_PREFIX) || !a.role) {
      next.push(a)
      continue
    }
    const r = want.get(a.role)
    if (r && live) {
      const fresh = liveActor(a, r, live, now)
      placed.add(a.role)
      if (sameLive(a, fresh)) next.push(a)
      else {
        changed = true
        next.push(fresh)
      }
    } else if (a.status !== 'done' && a.status !== 'failed') {
      changed = true
      next.push({ ...a, status: 'done', endedAt: now, tool: undefined, activity: 'done' })
    } else next.push(a)
  }
  for (const [role, r] of want) {
    if (placed.has(role) || !live) continue
    changed = true
    next.push(liveActor(undefined, r, live, now))
  }
  return changed ? next : actors
}

export function roleOf(type: string): DenRole | undefined {
  const m = /^ratchet:(.+)$/.exec(type)
  return m && ROLE_NAMES.includes(m[1]!) ? (m[1] as DenRole) : undefined
}

export const clip = (t: string, n = 40) => (t.length > n ? `${t.slice(0, n - 1)}…` : t)

/** One line for what a tool call is doing: `Edit app.ts`, `$ bun test`. */
export function summarize(tool: string, input: Readonly<Record<string, unknown>>): string {
  const s = (k: string) => (typeof input[k] === 'string' ? (input[k] as string) : '')
  const base = (p: string) => p.split('/').pop() || p
  switch (tool) {
    case 'Bash':
      return clip(`$ ${s('command').split('\n')[0]}`)
    case 'Read':
    case 'Write':
    case 'Edit':
    case 'MultiEdit':
      return `${tool} ${base(s('file_path'))}`
    case 'NotebookEdit':
      return `Edit ${base(s('notebook_path'))}`
    case 'Grep':
      return clip(`grep ${s('pattern')}`)
    case 'Glob':
      return clip(`glob ${s('pattern')}`)
    case 'WebFetch':
      return clip(`fetch ${s('url').replace(/^https?:\/\//, '')}`)
    case 'WebSearch':
      return clip(`search ${s('query')}`)
    case 'Agent':
      return clip(`→ ${s('subagent_type') || 'agent'}: ${s('description')}`)
    case 'Skill':
      return clip(`/${s('skill')}`)
    default:
      return clip(tool.replace(/^mcp__.+?__/, ''))
  }
}

function json(text: string): Record<string, unknown> | undefined {
  const i = text.indexOf('{')
  const j = text.lastIndexOf('}')
  if (i < 0 || j <= i) return undefined
  try {
    const v: unknown = JSON.parse(text.slice(i, j + 1))
    return v && typeof v === 'object' ? (v as Record<string, unknown>) : undefined
  } catch {
    return undefined
  }
}

/** What a ratchet agent's final answer says: the verdict and a short note. */
export function verdictOf(role: DenRole | undefined, answer: string): { verdict?: DenActor['verdict']; note?: string } {
  if (!role) return {}
  const j = json(answer)
  const findings = Array.isArray(j?.findings) ? (j!.findings as Array<Record<string, unknown>>) : []
  const top = findings[0]
  const topText = top ? clip(` · ${String(top.severity ?? '')} ${String(top.issue ?? '')}`.replace(/\s+/g, ' '), 44) : ''
  switch (role) {
    case 'review-arch':
    case 'review-break':
      if (j?.verdict === 'APPROVE') return { verdict: 'approve', note: 'APPROVE' }
      if (j?.verdict === 'CHANGES') return { verdict: 'changes', note: `CHANGES (${findings.length})${topText}` }
      return {}
    case 'visual':
      if (j?.verdict === 'PASS') return { verdict: 'approve', note: 'PASS' }
      if (j?.verdict === 'FAIL') return { verdict: 'changes', note: `FAIL (${findings.length})${topText}` }
      if (j?.verdict === 'INVALID') return { verdict: 'fail', note: 'INVALID capture' }
      return {}
    case 'spec': {
      const block = /cases:\s*\n([\s\S]*?)(?:\n[a-z]+:|$)/.exec(answer)?.[1] ?? ''
      const n = block.split('\n').filter(l => /^\s*-\s/.test(l)).length
      return { verdict: 'approve', note: n ? `${n} cases pinned` : 'spec written' }
    }
    case 'implement':
      return { verdict: 'approve', note: 'built it' }
  }
}

/** Rows of a ratchet plan table, by its header (`| id | checkpoint | … | status |`). */
export function parsePlan(text: string): DenPlanRow[] {
  const lines = text.split('\n').filter(l => l.trim().startsWith('|'))
  const header = lines.find(l => /\|\s*id\s*\|/i.test(l))
  if (!header) return []
  const cols = header.split('|').map(c => c.trim().toLowerCase())
  const iId = cols.indexOf('id')
  const iTitle = cols.indexOf('checkpoint')
  const iStatus = cols.indexOf('status')
  if (iId < 0 || iStatus < 0) return []
  return lines
    .map(l => l.split('|').map(c => c.trim()))
    .filter(c => /^cp\d+$/i.test(c[iId] ?? ''))
    .map(c => ({ id: c[iId]!, title: c[iTitle] ?? '', status: (c[iStatus] ?? '').toLowerCase() }))
}

export const currentRow = (plan: DenPlan | null) => plan?.rows.find(r => r.status !== 'approved')

/** The gate the run is at, from who's working and the current row's status. */
export function gateOf(plan: DenPlan | null, actors: readonly DenActor[]): string {
  const busy = (r: DenRole) => actors.some(a => a.role === r && a.status === 'working')
  if (busy('review-arch') || busy('review-break')) return 'B3'
  if (busy('visual')) return 'B2'
  if (busy('implement')) return 'B1'
  if (busy('spec')) return 'B0'
  const row = currentRow(plan)
  if (!row) return ''
  return { todo: 'B0', red: 'B1', green: 'B4', blocked: '⛔' }[row.status] ?? ''
}

export function trackLine(plan: DenPlan): string {
  const mark = (s: string, isCurrent: boolean) =>
    s === 'approved' ? '✓' : s === 'blocked' ? '✗' : isCurrent ? '◐' : '○'
  const cur = currentRow(plan)?.id
  return plan.rows
    .slice(0, 8)
    .map(r => `${r.id} ${mark(r.status, r.id === cur)}`)
    .join('━')
}

export function gateLine(gate: string): string {
  const order = ['B0', 'B1', 'B2', 'B3', 'B4']
  const at = order.indexOf(gate)
  return order.map((g, i) => `${g}${at < 0 ? '·' : i < at ? '✓' : i === at ? '◐' : '·'}`).join(' ')
}

export const ROLE_ICON: Record<DenRole, string> = {
  spec: '📋',
  implement: '🔨',
  visual: '📷',
  'review-arch': '📐',
  'review-break': '🪓',
}

export function iconOf(a: DenActor): string {
  if (a.role) return ROLE_ICON[a.role]
  if (a.kind === 'main') return '🦝'
  if (a.type === 'Explore') return '🔭'
  if (a.type === 'Plan') return '📘'
  return '👷'
}

export const kTok = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n))

export function statusText(mode: 'calm' | 'hyper', actors: readonly DenActor[], plan: DenPlan | null, paneShown: boolean): string | undefined {
  if (mode === 'hyper') {
    const row = currentRow(plan)
    const gate = gateOf(plan, actors)
    return `🦝 RATCHET${row ? ` ${row.id}` : ''}${gate ? ` ${gate}` : ''}`
  }
  if (paneShown) return undefined
  const n = actors.filter(a => a.kind === 'agent' && a.status === 'working').length
  return n ? `🦝 ${n} at work · /den` : undefined
}
