import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

const ROOT = '/repo'
const NOW = 1_700_000_000_000
const BATON = (next: string, stamp = '2026-10-03-1200') =>
  `# Handover — ratchet slugify\n<!-- scope: repo · roots: ${ROOT} · written: ${stamp} -->\n**Start here:** /ratchet run slugify --auto  (next: ${next} → B0)\n- standing OK: commit each green row\n`
const PATH = `${ROOT}/.claude/handovers/ratchet-slugify.md`

/** The engine beneath the relay, answered from memory; returns what it saw. */
function stage(engine: Engine, on: On, files: Record<string, string> = {}) {
  const clock = mock.clock(on, { now: NOW })
  const seen = {
    runs: [] as string[],
    installed: [] as string[][],
    logs: [] as string[],
    prompts: [] as string[],
    statuses: [] as (string | undefined)[],
  }
  const agents: { id: string; description: string; type: string; status: string; name?: string }[] = []
  on('agent.list', () => ({ value: agents }))
  on('prompt.submit', ($, e) => {
    seen.prompts.push(e.text)
    return { text: e.text }
  })
  on('turn.complete', ($, e) => ({ text: e.answer }))
  on('fs.read', ($, e) => {
    const hit = Object.keys(files).find(f => e.path === f || e.path.endsWith(`/${f}`))
    if (hit === undefined) throw new Error(`ENOENT ${e.path}`)
    return { value: files[hit] }
  })
  on('command.list', () => ({ value: [{ name: 'ratchet', description: 'r', source: 'plugin' as const, plugin: 'ratchet' }] }))
  on('command.run', async ($, e) => {
    // Core's /compact fires the compaction through every plugin's hooks.
    if (e.command === 'compact') {
      const r = await engine.session.compact({ instructions: e.args })
      if ('messages' in r && r.messages) seen.installed.push(r.messages.map(m => m.text))
      return { text: '' }
    }
    seen.runs.push(`${e.command} ${e.args}`)
    return { text: '' }
  })
  // Stands in for core's summary, which the relay must never reach.
  on('session.compact', () => ({ messages: [{ role: 'user' as const, text: 'core summary', toolUses: [] }] }))
  on('ui.log', ($, e) => {
    seen.logs.push(e.text)
    return { value: undefined }
  })
  on('ui.status', ($, e) => {
    seen.statuses.push(e.text)
    return { value: undefined }
  })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  const settle = async () => {
    await clock.advance(300)
    for (let i = 0; i < 20; i++) await clock.advance(0)
  }
  return { clock, seen, settle, agents }
}

const mainTurn = ($: Engine, answer: string, extra: object = {}) =>
  $.turn.complete({ answer, durationMs: 1000, isAborted: false, turnId: 't', reason: 'answer', ...extra } as never)

describe('the relay', () => {
  test('continue: resets the context to the baton, then starts the next run', async ($, on) => {
    const { seen, settle } = stage($, on, { [PATH]: BATON('cp3') })
    await mainTurn($, `cp2 locked.\n[ratchet] baton ${PATH} continue`)
    await settle()
    expect(seen.installed.length).toBe(1)
    expect(seen.installed[0]?.length).toBe(1) // the whole conversation is now one message
    expect(seen.installed[0]?.[0]).toMatch(/Start here:\*\* \/ratchet run slugify --auto/)
    expect(seen.runs).toEqual(['ratchet run slugify --auto --relay'])
  })

  test('stop: resets the context only', async ($, on) => {
    const { seen, settle } = stage($, on, { [PATH]: BATON('cp3') })
    await mainTurn($, `[ratchet] baton ${PATH} stop`)
    await settle()
    expect(seen.installed.length).toBe(1)
    expect(seen.runs).toEqual([])
  })

  test('a hand-typed marker with only the slug, in backticks, still resets', async ($, on) => {
    const { seen, settle } = stage($, on, { '.claude/handovers/ratchet-slugify.md': BATON('cp4') })
    await mainTurn($, 'cp3 locked.\n`[ratchet] baton slugify continue`')
    await settle()
    expect(seen.installed.length).toBe(1)
    expect(seen.runs).toEqual(['ratchet run slugify --auto --relay'])
  })

  test('ignores answers without the marker, subagent turns and aborted turns', async ($, on) => {
    const { seen, settle } = stage($, on, { [PATH]: BATON('cp3') })
    await mainTurn($, 'all done, no baton')
    await mainTurn($, `[ratchet] baton ${PATH} continue`, { agentId: 'a1' })
    await mainTurn($, `[ratchet] baton ${PATH} continue`, { reason: 'aborted', isAborted: true })
    await mainTurn($, `[ratchet] baton /repo/.claude/handovers/ratchet-missing.md continue`)
    await settle()
    expect(seen.installed).toEqual([])
    expect(seen.runs).toEqual([])
  })

  test('the same baton twice is a loop: the second relay is refused', async ($, on) => {
    const files = { [PATH]: BATON('cp3') }
    const { seen, settle } = stage($, on, files)
    await mainTurn($, `[ratchet] baton ${PATH} continue`)
    await settle()
    files[PATH] = BATON('cp3', '2026-10-03-1300') // only the stamp moved
    await mainTurn($, `[ratchet] baton ${PATH} continue`)
    await settle()
    expect(seen.runs.length).toBe(1)
    expect(seen.logs.join('\n')).toMatch(/no progress/)
  })

  test("a /compact of the person's own still gets core's summary", async ($, on) => {
    const { seen } = stage($, on)
    await $.command.run({ command: 'compact', args: '' })
    expect(seen.installed).toEqual([['core summary']])
  })
})

describe('leftover agents', () => {
  const agent = (name: string, type: string, status = 'running') => ({ id: name, description: name, type, status, name })

  test('running ratchet agents are asked to stop before the reset', async ($, on) => {
    const { seen, settle, agents } = stage($, on, { [PATH]: BATON('cp3') })
    agents.push(agent('impl-slugify-cp2', 'ratchet:implement'), agent('arch-slugify-cp2', 'ratchet:review-arch'))
    await mainTurn($, `[ratchet] baton ${PATH} continue`)
    await settle()
    expect(seen.prompts.length).toBe(1)
    expect(seen.prompts[0]).toMatch(/TaskStop: impl-slugify-cp2, arch-slugify-cp2/)
    expect(seen.installed).toEqual([])
    expect(seen.runs).toEqual([])

    // They stopped; the same marker comes back and relays, not read as a loop.
    agents.forEach(a => (a.status = 'killed'))
    await mainTurn($, `[ratchet] baton ${PATH} continue`)
    await settle()
    expect(seen.prompts.length).toBe(1)
    expect(seen.installed.length).toBe(1)
    expect(seen.runs).toEqual(['ratchet run slugify --auto --relay'])
  })

  test('agents still running after one nudge are named, and the reset goes ahead', async ($, on) => {
    const { seen, settle, agents } = stage($, on, { [PATH]: BATON('cp3') })
    agents.push(agent('break-slugify-cp2', 'ratchet:review-break'))
    await mainTurn($, `[ratchet] baton ${PATH} continue`)
    await settle()
    await mainTurn($, `[ratchet] baton ${PATH} continue`)
    await settle()
    expect(seen.prompts.length).toBe(1)
    expect(seen.logs.join('\n')).toMatch(/still running after the reset: break-slugify-cp2/)
    expect(seen.installed.length).toBe(1)
  })

  test("other agents, and ratchet's finished ones, don't count", async ($, on) => {
    const { seen, settle, agents } = stage($, on, { [PATH]: BATON('cp3') })
    agents.push(agent('scout', 'Explore'), agent('spec-slugify-cp2', 'ratchet:spec', 'completed'))
    await mainTurn($, `[ratchet] baton ${PATH} continue`)
    await settle()
    expect(seen.prompts).toEqual([])
    expect(seen.installed.length).toBe(1)
  })
})

describe('the --relay flag', () => {
  test('is added to /ratchet run once, and to nothing else', async ($, on) => {
    const { seen } = stage($, on)
    await $.command.run({ command: 'ratchet', args: 'run slugify --auto' })
    await $.command.run({ command: 'ratchet', args: 'run --relay' })
    await $.command.run({ command: 'ratchet', args: 'status' })
    await $.command.run({ command: 'den', args: 'demo' })
    expect(seen.runs).toEqual(['ratchet run slugify --auto --relay', 'ratchet run --relay', 'ratchet status', 'den demo'])
  })

  test('is left off when the repo turns the relay off', async ($, on) => {
    const { seen } = stage($, on, { '.claude/ratchet/config.json': '{"relay": false}' })
    await $.command.run({ command: 'ratchet', args: 'run' })
    expect(seen.runs).toEqual(['ratchet run'])
  })
})

describe('dream proposals', () => {
  const START = { cwd: ROOT, surface: 'terminal', isInteractive: true } as const
  const PENDING = '.claude/ratchet/dreams/pending.json'

  test('are announced at session start from the index under home', async ($, on) => {
    const index = { bundles: [{ bundle: '2026-10-05', items: 2 }, { bundle: '2026-10-06', items: 1 }] }
    const { seen } = stage($, on, { [`/Users/me/${PENDING}`]: JSON.stringify(index) })
    on('env.get', () => ({ value: '/Users/me' }))
    await $.session.start(START)
    expect(seen.logs).toEqual(['🦝 3 dream proposals wait for you · /ratchet dream'])
  })

  test('say nothing without an index, or with an empty or broken one', async ($, on) => {
    const files: Record<string, string> = {}
    const { seen } = stage($, on, files)
    on('env.get', () => ({ value: '/Users/me' }))
    for (const text of [undefined, '{"bundles": []}', '{"bundles": ']) {
      if (text === undefined) delete files[`/Users/me/${PENDING}`]
      else files[`/Users/me/${PENDING}`] = text
      await $.session.start(START)
    }
    expect(seen.logs).toEqual([])
  })
})

describe('the status line', () => {
  const LIVE = '.claude/ratchet/live.json'
  const START = { cwd: ROOT, surface: 'terminal', isInteractive: true } as const
  const live = (extra: object = {}) =>
    JSON.stringify({ active: true, slug: 'slugify', cp: 'cp2', gate: 'B1', round: 2, roles: [], updated: new Date(NOW - 7 * 60_000).toISOString(), ...extra })

  test('shows the checkpoint, gate, round and minutes while a run is live, and clears when it ends', async ($, on) => {
    const files: Record<string, string> = { [LIVE]: live() }
    const { clock, seen, settle } = stage($, on, files)
    await $.session.start(START)
    await clock.settle()
    expect(seen.statuses).toEqual(['ratchet cp2 · B1 r2 · 7m'])

    await clock.advance(5_000)
    await settle()
    expect(seen.statuses.length).toBe(1) // the same line is not set twice

    await clock.advance(55_000)
    await settle()
    expect(seen.statuses).toEqual(['ratchet cp2 · B1 r2 · 7m', 'ratchet cp2 · B1 r2 · 8m'])

    files[LIVE] = live({ active: false })
    await clock.advance(5_000)
    await settle()
    expect(seen.statuses[2]).toBeUndefined()
    expect(seen.statuses.length).toBe(3)
  })

  test('refreshes at the end of a turn without waiting for the poll', async ($, on) => {
    const files: Record<string, string> = {}
    const { clock, seen } = stage($, on, files)
    await $.session.start(START)
    await clock.settle()
    expect(seen.statuses).toEqual([])
    files[LIVE] = live()
    await mainTurn($, 'done')
    await clock.settle()
    expect(seen.statuses).toEqual(['ratchet cp2 · B1 r2 · 7m'])
  })

  test('shows nothing for a stale, inactive or unreadable live file', async ($, on) => {
    const files: Record<string, string> = { [LIVE]: live({ updated: new Date(NOW - 7 * 3_600_000).toISOString() }) }
    const { clock, seen, settle } = stage($, on, files)
    await $.session.start(START)
    for (const text of [live({ active: false }), '{"active": ', '[]']) {
      files[LIVE] = text
      await clock.advance(5_000)
      await settle()
    }
    delete files[LIVE]
    await clock.advance(5_000)
    await settle()
    expect(seen.statuses).toEqual([])
  })
})
