import { describe, expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { blockedOp, register } from './guard'

// Each command a ratchet agent may not run, with the op it is named for.
const DENIED: [string, string][] = [
  ['git stash', 'git stash'],
  ['git stash pop', 'git stash'],
  ['git reset --hard HEAD~1', 'git reset --hard'],
  ['git checkout -- src/a.ts', 'git checkout --'],
  ['git checkout HEAD -- src/a.ts', 'git checkout --'],
  ['git checkout .', 'git checkout .'],
  ['git restore src/a.ts', 'git restore'],
  ['git restore --staged --worktree .', 'git restore'],
  ['git clean -fd', 'git clean'],
  ['git commit -m "x"', 'git commit'],
  ['git push origin main', 'git push'],
  ['git merge --no-verify topic', '--no-verify'],
  // Chained, prefixed, wrapped and nested.
  ['cd packages/app && git stash', 'git stash'],
  ['bun test; git reset --hard', 'git reset --hard'],
  ['git status | tee log && git push', 'git push'],
  ['FOO=1 BAR="a b" git clean -fd', 'git clean'],
  ['git -C ../other -c core.pager=cat commit -m x', 'git commit'],
  ['sudo -E git push', 'git push'],
  ['timeout 30 git push', 'git push'],
  ['(cd x && git stash)', 'git stash'],
  ['echo "$(git stash)"', 'git stash'],
  ['bash -c "cd x && git stash"', 'git stash'],
  ['if true; then git push; fi', 'git push'],
  ['/usr/bin/git push', 'git push'],
  ['git status\ngit commit -am x', 'git commit'],
]

const ALLOWED = [
  'git status --short',
  'git diff --stat HEAD~1',
  'git log --oneline -n 5 | head',
  'git show HEAD:src/a.ts',
  'git restore --staged src/a.ts',
  'git reset HEAD src/a.ts',
  'git reset --soft HEAD~1',
  'git checkout -b cp3-work',
  'git add -A',
  'git commit-tree HEAD^{tree} -m x',
  'bun test 2>&1 | tail -20',
  'bash ratchet.sh restore .claude/ratchet/evidence/s/cp1',
  // Text that only mentions a command is not the command.
  'echo "git stash && git commit"',
  "rg 'git push' docs",
  'git status # then git stash',
  'cat <<< "git stash"',
  "cat <<'EOF' > notes.md\ngit commit -m x\ngit stash\nEOF",
]

describe('the deny list', () => {
  test('names each destructive command, however it is chained, prefixed or nested', () => {
    for (const [command, op] of DENIED) expect(blockedOp(command), command).toBe(op)
  })

  test('lets read-only git, other tools and text that only mentions git through', () => {
    for (const command of ALLOWED) expect(blockedOp(command), command).toBeUndefined()
  })
})

type Hook = ($: unknown, e: unknown, next: (e: unknown) => unknown) => Promise<unknown>
const RAN = { result: 'ran' }

/** The module's Bash hook as registered: `$.tool.call` drops `agentId`, so a subagent's call can't be raised through the engine. */
function bashHook(): Hook {
  const got: { hook?: Hook } = {}
  const on = ((...args: unknown[]) => {
    got.hook = args[args.length - 1] as Hook
  }) as unknown as On
  register(on, {} as never)
  if (!got.hook) throw new Error('the guard hooked nothing')
  return got.hook
}

let worlds = 0

/** A clock and the live file, as the hook reads them. */
function world(file: ((now: number) => string) | undefined) {
  // Each world starts an hour after the last: the module's cache from an earlier test has expired.
  const w = { now: 1_700_000_000_000 + worlds++ * 3_600_000, file, reads: 0 }
  const $ = {
    clock: { now: async () => w.now },
    fs: {
      read: async () => {
        w.reads++
        if (!w.file) throw new Error('ENOENT')
        return w.file(w.now)
      },
    },
  }
  return { w, $ }
}

const live =
  (ageMs = 60_000, extra: object = {}) =>
  (now: number) =>
    JSON.stringify({ active: true, slug: 's', cp: 'cp2', gate: 'B1', round: 1, roles: [], updated: new Date(now - ageMs).toISOString(), ...extra })

const call = (hook: Hook, $: unknown, command: string, agentId?: string) =>
  hook($, { tool: 'Bash', command, ...(agentId ? { agentId } : {}) }, async () => RAN)

const denyOf = async (result: Promise<unknown>) => ((await result) as { deny?: string }).deny

describe('the hook', () => {
  test('denies a subagent while a run is live, and never the main loop', async () => {
    const { w, $ } = world(live())
    const hook = bashHook()
    expect(await denyOf(call(hook, $, 'cd app && git stash', 'agent-1'))).toMatch(/ratchet is live.*git stash.*RS restore and RS check/)
    expect(await call(hook, $, 'git stash')).toBe(RAN)
    expect(await call(hook, $, 'git status', 'agent-1')).toBe(RAN)
    expect(w.reads).toBe(1) // only the denied call needed the file
  })

  test('lets everything through when the live file is missing, bad, inactive or stale', async () => {
    const hook = bashHook()
    const files: [string, ((now: number) => string) | undefined][] = [
      ['missing', undefined],
      ['not json', () => '{"active": tru'],
      ['inactive', live(60_000, { active: false })],
      ['six hours old', live(6 * 3_600_000)],
    ]
    for (const [why, file] of files) {
      expect(await call(hook, world(file).$, 'git commit -m x', 'agent-1'), why).toBe(RAN)
    }
    expect(await denyOf(call(hook, world(live(6 * 3_600_000 - 1000)).$, 'git commit -m x', 'agent-1'))).toMatch(/git commit/)
  })

  test('reads the live file once in a few seconds', async () => {
    const { w, $ } = world(live())
    const hook = bashHook()
    expect(await denyOf(call(hook, $, 'git push', 'agent-1'))).toMatch(/git push/)
    w.file = live(60_000, { active: false }) // the run ends
    expect(await denyOf(call(hook, $, 'git push', 'agent-1'))).toMatch(/git push/) // the cached answer
    expect(w.reads).toBe(1)
    w.now += 4_000
    expect(await call(hook, $, 'git push', 'agent-1')).toBe(RAN)
    expect(w.reads).toBe(2)
  })
})

test('the plugin loads under the engine and lets the main loop through', async ($, on) => {
  on('tool.call', () => ({ result: { stdout: '', stderr: '', interrupted: false }, text: 'ran' }) as never)
  const r = await $.tool.call({ tool: 'Bash', command: 'git stash' })
  expect((r as { text?: string }).text).toBe('ran')
})
