import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

const ROOT = '/repo'
const BATON = (next: string, stamp = '2026-10-03-1200') =>
  `# Handover — ratchet slugify\n<!-- scope: repo · roots: ${ROOT} · written: ${stamp} -->\n**Start here:** /ratchet run slugify --auto  (next: ${next} → B0)\n- standing OK: commit each green row\n`
const PATH = `${ROOT}/.claude/handovers/ratchet-slugify.md`

/** The engine beneath the relay, answered from memory; returns what it saw. */
function stage(engine: Engine, on: On, files: Record<string, string> = {}) {
  const clock = mock.clock(on, { now: 1_700_000_000_000 })
  const seen = { runs: [] as string[], installed: [] as string[][], logs: [] as string[] }
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
  const settle = async () => {
    await clock.advance(300)
    for (let i = 0; i < 20; i++) await clock.advance(0)
  }
  return { clock, seen, settle }
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
