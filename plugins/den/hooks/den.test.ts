import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

import { gateOf, parsePlan, roleOf, summarize, trackLine, verdictOf } from './logic'
import { compose, hyperCast, pack, ROWS } from './scene'

const PANE = {
  plugin: 'den',
  component: 'Pane',
  requestId: 'den',
  props: { title: '🦝 den', isFocused: false, bodyColumns: 46, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} },
} as const

/** Everything the den asks of the engine, answered from memory. */
function stage(on: On) {
  mock.store(on)
  const clock = mock.clock(on, { now: 1_700_000_000_000 })
  on('ui.open', () => ({ value: { isPlaced: true as const, id: 'den', title: 'den' } }))
  on('agent.spawn', ($, e) => ({ model: 'claude-sonnet-5', agentId: `agent-${e.description}` }))
  on('turn.complete', ($, e) => ({ text: e.answer }))
  return clock
}

const spawn = ($: Engine, subagentType: string, description: string) =>
  $.agent.spawn({
    tool_use_id: `tu-${description}`,
    prompt: 'go',
    description,
    subagentType,
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'claude-opus-5-5',
    background: true,
    fork: false,
  })

const finish = ($: Engine, agentId: string, answer: string) =>
  $.turn.complete({ answer, durationMs: 4200, isAborted: false, turnId: 't', agentId, reason: 'answer', usage: { input_tokens: 9000, output_tokens: 1000, model: 'claude-sonnet-5' } as never })

async function paneText($: Engine, surface: 'terminal' | 'desktop' = 'terminal') {
  const ui = await $.ui.mount({ ...PANE, surface })
  const texts = (await ui.findAll({ type: 'Text' })).map(t => t.text ?? '').join('\n')
  const hasScene = (await ui.find({ key: 'scene' })) !== undefined
  await ui.unmount()
  return { texts, hasScene }
}

describe('reading events', () => {
  test('ratchet roles come from the agent type', () => {
    expect(roleOf('ratchet:review-break')).toBe('review-break')
    expect(roleOf('ratchet:nope')).toBeUndefined()
    expect(roleOf('Explore')).toBeUndefined()
  })

  test('tool calls read as one short line', () => {
    expect(summarize('Edit', { file_path: '/repo/src/app.ts' })).toBe('Edit app.ts')
    expect(summarize('Bash', { command: 'bun test\necho hi' })).toBe('$ bun test')
    expect(summarize('mcp__github__create_issue', {})).toBe('create_issue')
  })

  test('reviewer, visual and spec verdicts', () => {
    const changes = JSON.stringify({ verdict: 'CHANGES', findings: [{ severity: 'high', issue: 'empty input crashes' }, {}] })
    expect(verdictOf('review-break', changes)).toEqual({ verdict: 'changes', note: 'CHANGES (2) · high empty input crashes' })
    expect(verdictOf('review-arch', 'prose then {"verdict":"APPROVE","findings":[]}')).toEqual({ verdict: 'approve', note: 'APPROVE' })
    expect(verdictOf('visual', '{"verdict":"INVALID"}').verdict).toBe('fail')
    expect(verdictOf('spec', 'files: a\ncases:\n- one\n- two\nred: x').note).toBe('2 cases pinned')
    expect(verdictOf(undefined, '{"verdict":"APPROVE"}')).toEqual({})
  })

  test('plan tables by header, with or without a target column', () => {
    const plan = `| id | checkpoint | target | status | base |\n| -- | -- | -- | -- | -- |\n| cp1 | skeleton | p | approved | x |\n| cp2 | header | p | red | |`
    expect(parsePlan(plan)).toEqual([
      { id: 'cp1', title: 'skeleton', status: 'approved' },
      { id: 'cp2', title: 'header', status: 'red' },
    ])
    expect(parsePlan('| id | checkpoint | status |\n| cp1 | a | todo |')[0]?.status).toBe('todo')
    const p = { slug: 's', rows: parsePlan(plan) }
    expect(gateOf(p, [])).toBe('B1')
    expect(trackLine(p)).toBe('cp1 ✓━cp2 ◐')
  })

  test('hyper draws one raccoon per agent at work, not a fixed crowd', () => {
    const look = (id: string, type: string, status: 'working' | 'done', extra = {}) => ({
      id, kind: 'agent' as const, type, role: roleOf(type), status, bornAt: 0, ...extra,
    })
    const now = 100_000
    expect(hyperCast({ now, actors: [look('s', 'ratchet:spec', 'working')] })).toEqual({ crew: ['spec'], minions: 0 })
    expect(hyperCast({ now, actors: [look('s', 'ratchet:spec', 'working'), look('e', 'Explore', 'working')] }).minions).toBe(1)
    expect(hyperCast({ now, actors: [] })).toEqual({ crew: [], minions: 0 })
    // A finished reviewer lingers just long enough to show its verdict.
    const arch = (endedAt: number) => look('a', 'ratchet:review-arch', 'done', { endedAt })
    expect(hyperCast({ now, actors: [arch(now - 1000)] }).crew).toEqual(['review-arch'])
    expect(hyperCast({ now, actors: [arch(now - 60_000)] }).crew).toEqual([])
  })

  test('frames pack to exactly columns × rows cells', () => {
    for (const mode of ['calm', 'hyper'] as const) {
      const frame = compose({ mode, actors: [], beats: [], now: 0 }, 46, 3)
      expect(frame.h).toBe(ROWS[mode] * 2)
      expect(pack(frame).length).toBe(Math.ceil((46 * ROWS[mode] * 12) / 3) * 4)
    }
  })
})

describe('the den in a session', () => {
  test('draws a Raster on the terminal and a text roster on desktop', async ($, on) => {
    stage(on)
    const term = await paneText($, 'terminal')
    expect(term.hasScene).toBe(true)
    expect(term.texts).toMatch(/den · all quiet/)
    const desk = await paneText($, 'desktop')
    expect(desk.hasScene).toBe(false)
    expect(desk.texts).toMatch(/den/)
  })

  test('a subagent climbs out, works, and reports back with its tokens', async ($, on) => {
    stage(on)
    await spawn($, 'Explore', 'find auth')
    expect((await paneText($)).texts).toMatch(/Explore\s+find auth/)
    await finish($, 'agent-find auth', 'found it in src/auth.ts')
    expect((await paneText($)).texts).toMatch(/Explore\s+done · 10k tok/)
  })

  test('a ratchet agent flips the den to hyper; a reviewer verdict lands in the roster', async ($, on) => {
    stage(on)
    await spawn($, 'ratchet:review-break', 'cp1 break it')
    let { texts } = await paneText($)
    expect(texts).toMatch(/RATCHET/)
    expect(texts).toMatch(/review-break\s+cp1 break it/)
    await finish($, 'agent-cp1 break it', JSON.stringify({ verdict: 'CHANGES', findings: [{ severity: 'high', issue: 'empty input' }] }))
    ;({ texts } = await paneText($))
    expect(texts).toMatch(/CHANGES \(1\) · high empty input/)
  })

  test('the helper reporting a changed spec sounds the tamper alarm', async ($, on) => {
    stage(on)
    on('tool.call', () => ({ result: { stdout: '', stderr: '', interrupted: false }, text: 'CHANGED  src/a.test.ts\nexit=1' }) as never)
    await $.tool.call({ tool: 'Bash', command: 'bash ~/x/ratchet.sh check .claude/ratchet/evidence/s/*' })
    const { texts } = await paneText($)
    expect(texts).toMatch(/RATCHET/)
    expect(texts).toMatch(/TAMPERING CAUGHT/)
  })

  test('/den demo plays through a lock, YOUR TURN and the plan finishing', async ($, on) => {
    const clock = stage(on)
    const r = await $.command.run({ command: 'den', args: 'demo' } as never)
    expect(r.text).toMatch(/demo/)
    await clock.advance(41_000)
    let { texts } = await paneText($)
    expect(texts).toMatch(/RATCHET · demo · cp2 B4/)
    expect(texts).toMatch(/waits for you/)
    await clock.advance(10_000)
    ;({ texts } = await paneText($))
    expect(texts).toMatch(/plan done/)
    await clock.advance(8_000)
    ;({ texts } = await paneText($))
    expect(texts).toMatch(/demo over/)
    expect(texts).not.toMatch(/RATCHET/)
  })
})
