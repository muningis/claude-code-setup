import type { EngineInterface, Register } from 'claude-code'

// ratchet's relay: at each checkpoint's end the skill writes a minimal baton
// (`RS baton`) and ends its turn with a marker; this resets the context to that
// baton and, under --auto, starts the next run. A skill can't clear its own
// context; a mod can.

type $ = EngineInterface

const MARKER = /^\[ratchet\] baton (.+\/\.claude\/handovers\/ratchet-([A-Za-z0-9._-]+)\.md) (continue|stop)\s*$/m
const MAX_RELAYS = 30 // per session: a run that keeps relaying without ending is a loop

// Module state: a hot reload drops it, which at worst skips one reset.
let pending: string | null = null // the baton the next compaction installs
let lastBaton = ''
let relays = 0

const isRatchet = (command: string) => command === 'ratchet' || command.endsWith(':ratchet')

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

async function relay($: $, slug: string, how: string, baton: string) {
  if (!(await compactTo($, baton))) {
    $.ui.log('🦝 ratchet relay: the context reset failed; carrying on without it')
  }
  if (how === 'continue') await $.command.run({ command: await ratchetCommand($), args: `run ${slug} --auto --relay` })
}

export const register: Register = on => {
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
    if (e.agentId || e.reason !== 'answer') return result
    const hit = MARKER.exec(e.answer)
    if (!hit) return result
    const [, path, slug, how] = hit
    let baton: string
    try {
      baton = await $.fs.read(path)
    } catch {
      return result // marker without a file: nothing to hand over
    }
    const same = baton.replace(/ · written: \S+/, '') === lastBaton
    if (same || relays >= MAX_RELAYS) {
      $.ui.log(`🦝 ratchet relay: stopped (${same ? 'same baton twice, no progress' : `${MAX_RELAYS} relays this session`})`)
      return result
    }
    lastBaton = baton.replace(/ · written: \S+/, '')
    relays++
    // After the turn has ended: compaction is refused while one runs.
    $.clock.after(250, () => void relay($, slug, how, baton))
    return result
  })
}
