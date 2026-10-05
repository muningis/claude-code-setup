import type { EngineInterface, Register, Timer } from 'claude-code'

import { register as registerGuard } from './guard'

// ratchet's relay: at each checkpoint's end the skill writes a minimal baton
// (`RS baton`) and ends its turn with a marker; this resets the context to that
// baton and, under --auto, starts the next run. A skill can't clear its own
// context; a mod can. It also keeps the status line while a run is live, and
// says at session start when dream proposals wait for review.

type $ = EngineInterface

const MARKER = /^\[ratchet\] baton (.+\/\.claude\/handovers\/ratchet-([A-Za-z0-9._-]+)\.md) (continue|stop)\s*$/m
// A lead that types the marker by hand can drop the path (one real reset in four was lost
// that way). The slug alone names the file, relative to the session folder.
const SHORT_MARKER = /^\[ratchet\] baton (?:ratchet-)?([A-Za-z0-9._-]+?)(?:\.md)? (continue|stop)\s*$/m
const MAX_RELAYS = 30 // per session: a run that keeps relaying without ending is a loop
// The lead's own `RS baton` call. Its output holds the full marker, printed by code. A lead
// that then shortens the marker in its answer (a real one wrote `[ratchet] baton continue`,
// then copied that form for four more checkpoints) still hands over.
const BATON_RUN = /ratchet\.sh['"]?\s+baton\s+\S+\s+(?:continue|stop)\b/

type Hit = { path: string; slug: string; how: string }

export function parseMarker(answer: string): Hit | null {
  // Markdown can wrap the line in backticks.
  const text = answer.replace(/`/g, '')
  const full = MARKER.exec(text)
  if (full) return { path: full[1]!, slug: full[2]!, how: full[3]! }
  const short = SHORT_MARKER.exec(text)
  if (short) return { path: `.claude/handovers/ratchet-${short[1]}.md`, slug: short[1]!, how: short[2]! }
  return null
}
const LIVE_FILE = '.claude/ratchet/live.json'
const LIVE_MAX_AGE_MS = 6 * 60 * 60 * 1000 // a crashed run leaves `active: true` behind
const STATUS_POLL_MS = 5000
// Under the home folder, not the session's: the nightly dream is one for the whole machine.
const DREAM_PENDING = '.claude/ratchet/dreams/pending.json'

// Module state: a hot reload drops it, which at worst skips one reset.
let pending: string | null = null // the baton the next compaction installs
let armed: Hit | null = null // what RS baton printed in this main-loop turn, or what a nudge waits on
let lastBaton = ''
let nudged = '' // the baton whose leftover agents were already asked to stop
let relays = 0
let poll: Timer | undefined
let shown: string | undefined // the status line this mod set; none yet

const isRatchet = (command: string) => command === 'ratchet' || command.endsWith(':ratchet')

/** The marker in a Bash result, from its stdout or its text. */
function batonPrinted(result: unknown): Hit | null {
  const r = result as { result?: { stdout?: unknown }; text?: unknown } | null
  const out = [r?.result?.stdout, r?.text].filter((s): s is string => typeof s === 'string').join('\n')
  const full = MARKER.exec(out)
  return full ? { path: full[1]!, slug: full[2]!, how: full[3]! } : null
}

async function relayOn($: $) {
  try {
    const config = JSON.parse(await $.fs.read('.claude/ratchet/config.json')) as { relay?: boolean }
    return config.relay !== false
  } catch {
    return true // no config yet (first run) or unreadable: the default
  }
}

async function ratchetCommand($: $) {
  const commands = await $.command.list()
  return (commands.find(c => c.name === 'ratchet') ?? commands.find(c => isRatchet(c.name)))?.name ?? 'ratchet'
}

// Through `/compact`, not `$.session.compact()`: a plugin's own compaction skips
// its own session.compact hook, and that hook is what installs the baton.
async function compactTo($: $, baton: string) {
  pending = baton
  try {
    await $.command.run({ command: 'compact', args: 'ratchet relay' })
  } catch {
    // Unknown command or the session not idle: reported below.
  }
  const installed = pending === null
  pending = null
  return installed
}

// ratchet's agents still running: each one would outlive the reset, idle.
async function leftovers($: $) {
  const agents = await $.agent.list()
  return agents.filter(a => a.type.startsWith('ratchet:') && a.status === 'running').map(a => a.name ?? a.description)
}

async function relay($: $, slug: string, how: string, baton: string) {
  if (!(await compactTo($, baton))) {
    $.ui.log('🦝 ratchet relay: the context reset failed; carrying on without it')
  }
  if (how === 'continue') await $.command.run({ command: await ratchetCommand($), args: `run ${slug} --auto --relay` })
}

/** The status line for a live run, or undefined when none is going. */
function statusLine(text: string, now: number) {
  let live: Record<string, unknown> | null
  try {
    live = JSON.parse(text)
  } catch {
    return undefined
  }
  const at = typeof live?.updated === 'string' ? Date.parse(live.updated) : NaN
  if (live?.active !== true || !Number.isFinite(at) || now - at >= LIVE_MAX_AGE_MS) return undefined
  const cp = typeof live.cp === 'string' ? live.cp : ''
  const round = typeof live.round === 'number' ? ` r${live.round}` : ''
  const gate = typeof live.gate === 'string' && live.gate ? `${live.gate}${round}` : ''
  const minutes = Math.max(0, Math.floor((now - at) / 60_000))
  return [`ratchet${cp ? ` ${cp}` : ''}`, gate, `${minutes}m`].filter(Boolean).join(' · ')
}

/** The session-start line for dream proposals that wait for review, or undefined. */
export function dreamNotice(text: string) {
  let index: { bundles?: unknown }
  try {
    index = JSON.parse(text)
  } catch {
    return undefined
  }
  const bundles = Array.isArray(index?.bundles) ? (index.bundles as { items?: unknown }[]) : []
  const items = bundles.reduce((n, b) => n + (typeof b?.items === 'number' && b.items > 0 ? b.items : 0), 0)
  if (items === 0) return undefined
  return `🦝 ${items} dream proposal${items === 1 ? '' : 's'} wait for you · /ratchet dream`
}

async function announceDreams($: $) {
  try {
    const home = await $.env.get('HOME')
    if (!home) return
    const notice = dreamNotice(await $.fs.read(`${home}/${DREAM_PENDING}`))
    if (notice) $.ui.log(notice)
  } catch {
    // No index means no proposals.
  }
}

async function refreshStatus($: $) {
  try {
    const now = await $.clock.now()
    const status = statusLine(await $.fs.read(LIVE_FILE).catch(() => ''), now)
    if (status === shown) return
    shown = status
    await $.ui.status(status)
  } catch {
    // A status line is never worth a failed hook.
  }
}

export const register: Register = (on, options) => {
  // A plugin names one hooks module: the guard rides in this one.
  registerGuard(on, options)

  on('session.start', async ($, e, next) => {
    poll?.cancel()
    poll = $.clock.every(STATUS_POLL_MS, () => void refreshStatus($))
    await refreshStatus($)
    await announceDreams($)
    return next(e)
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const result = await next(e)
    if (!e.agentId && BATON_RUN.test(e.command)) armed = batonPrinted(result)
    return result
  })

  // The flag that tells the skill to hand over: present only when this mod is.
  on('command.run', async ($, e, next) => {
    if (!isRatchet(e.command) || !/^\s*run\b/.test(e.args) || /(^|\s)--relay\b/.test(e.args)) return next(e)
    return (await relayOn($)) ? next({ ...e, args: `${e.args.trim()} --relay` }) : next(e)
  })

  on('session.compact', ($, e, next) => {
    if (pending === null || e.trigger === 'precompute' || e.agentId) return next(e)
    const baton = pending
    pending = null
    const text = `[ratchet relay] Context reset at a checkpoint boundary. The baton:\n\n${baton}`
    return { messages: [{ role: 'user' as const, text, toolUses: [] }] }
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    await refreshStatus($)
    if (e.agentId) return result
    // What RS baton printed comes first; the answer's own marker is the fallback. A turn that
    // the human stopped hands nothing over.
    const hit = e.reason === 'answer' ? (armed ?? parseMarker(e.answer)) : null
    armed = null
    if (!hit) return result
    const { path, slug, how } = hit
    let baton: string
    try {
      baton = await $.fs.read(path)
    } catch {
      return result // marker without a file: nothing to hand over
    }
    const key = baton.replace(/ · written: \S+/, '')
    const same = key === lastBaton
    if (same || relays >= MAX_RELAYS) {
      $.ui.log(`🦝 ratchet relay: stopped (${same ? 'same baton twice, no progress' : `${MAX_RELAYS} relays this session`})`)
      return result
    }
    const left = await leftovers($)
    if (left.length > 0 && nudged !== key) {
      // Once per baton; the repeated marker then relays, so it isn't a loop. The reply to the
      // nudge relays this baton, whatever form its marker takes.
      nudged = key
      armed = hit
      const text = `[ratchet relay] Before the reset, stop these with TaskStop: ${left.join(', ')}. Then end your turn with the same baton marker line.`
      $.clock.after(250, () => void $.prompt.submit({ text }))
      return result
    }
    if (left.length > 0) $.ui.log(`🦝 ratchet relay: still running after the reset: ${left.join(', ')}`)
    lastBaton = key
    relays++
    // After the turn has ended: compaction is refused while one runs.
    $.clock.after(250, () => void relay($, slug, how, baton))
    return result
  })
}
