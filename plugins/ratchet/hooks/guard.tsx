import type { EngineInterface, Register } from 'claude-code'

// ratchet's guard: while a run is live, no subagent may rewrite the tree or the
// history. A workflow's agents carry ids that `$.agent.list()` never names, so the
// guard can't tell which agent is which; the live file says a run is going, and
// every subagent is held to it. The main loop is never held.

type $ = EngineInterface

const LIVE_FILE = '.claude/ratchet/live.json'
const MAX_AGE_MS = 6 * 60 * 60 * 1000 // a crashed run leaves `active: true` behind
const CACHE_MS = 3000
const MAX_DEPTH = 3 // nested `bash -c` / `eval`

// Anywhere in the text, quoted or not: a skipped hook is never an agent's call.
const NO_VERIFY = /(^|[^\w-])--no-verify(?![\w-])/

const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh'])
// Words that put another command, or a clause, in front of the one that runs.
const WRAPPERS = new Set([
  'sudo', 'doas', 'env', 'command', 'builtin', 'exec', 'nohup', 'nice', 'ionice',
  'time', 'timeout', 'xargs', 'stdbuf', 'setsid', 'caffeinate', 'watch', 'rtk',
])
const WRAPPER_ARGS = /^(-.*|\{\}|\d+(\.\d+)?[smhd]?)$/
const KEYWORDS = new Set(['!', '{', '}', 'if', 'then', 'else', 'elif', 'fi', 'do', 'done', 'while', 'until'])
const GIT_VALUE_OPTIONS = new Set(['-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env', '--super-prefix'])

type Heredoc = { tag: string; stripTabs: boolean; runs: boolean }

const baseName = (word: string) => word.slice(word.lastIndexOf('/') + 1).replace(/\.exe$/i, '')
const isAssignment = (word: string) => /^[A-Za-z_]\w*=/.test(word)

const closing = (src: string, quote: string, from: number) => {
  const at = src.indexOf(quote, from)
  return at < 0 ? src.length : at
}

function closingParen(src: string, from: number) {
  let depth = 1
  for (let i = from; i < src.length; i++) {
    const c = src.charAt(i)
    if (c === '(') depth++
    else if (c === ')' && --depth === 0) return i
  }
  return src.length
}

function heredocTag(src: string, from: number) {
  let i = from
  const stripTabs = src.charAt(i) === '-'
  if (stripTabs) i++
  while (src.charAt(i) === ' ' || src.charAt(i) === '\t') i++
  const quote = src.charAt(i)
  if (quote === "'" || quote === '"') {
    const end = closing(src, quote, i + 1)
    return { tag: src.slice(i + 1, end), stripTabs, end: end + 1 }
  }
  const start = i
  while (i < src.length && !/[\s;&|()<>]/.test(src.charAt(i))) i++
  return { tag: src.slice(start, i), stripTabs, end: i }
}

/** Skips the heredoc bodies that begin at `from`; a shell's body is scanned as commands. */
function skipHeredocs(src: string, from: number, queue: Heredoc[], scan: (body: string) => void) {
  let i = from
  for (const h of queue.splice(0)) {
    const start = i
    let end = src.length // an unterminated body runs to the end
    while (i < src.length) {
      const eol = src.indexOf('\n', i)
      const next = eol < 0 ? src.length : eol + 1
      const line = src.slice(i, eol < 0 ? src.length : eol).replace(/\r$/, '')
      if ((h.stripTabs ? line.replace(/^\t+/, '') : line) === h.tag) {
        end = i
        i = next
        break
      }
      i = next
    }
    if (h.runs) scan(src.slice(start, end))
  }
  return i
}

/**
 * The simple commands of a shell line, as word lists with the quotes removed. It
 * splits on `;` `&` `|` newlines and parentheses, skips comments and heredoc bodies,
 * and reads `$(…)` and backticks as commands of their own.
 */
function simpleCommands(src: string, depth = 0): string[][] {
  const out: string[][] = []
  const queue: Heredoc[] = []
  let cmd: string[] = []
  let word = ''
  let isWord = false // an empty quoted string is a word too

  const endWord = () => {
    if (isWord) cmd.push(word)
    word = ''
    isWord = false
  }
  const endCommand = () => {
    endWord()
    if (cmd.length > 0) out.push(cmd)
    cmd = []
  }
  const scan = (text: string) => {
    if (depth < MAX_DEPTH) out.push(...simpleCommands(text, depth + 1))
  }

  let i = 0
  while (i < src.length) {
    const c = src.charAt(i)
    const n = src.charAt(i + 1)
    if (c === '\\') {
      if (n !== '' && n !== '\n') {
        word += n
        isWord = true
      }
      i += 2
    } else if (c === "'") {
      const end = closing(src, "'", i + 1)
      word += src.slice(i + 1, end)
      isWord = true
      i = end + 1
    } else if (c === '"') {
      isWord = true
      i++
      while (i < src.length && src.charAt(i) !== '"') {
        const d = src.charAt(i)
        if (d === '\\') {
          word += src.charAt(i + 1)
          i += 2
        } else if (d === '$' && src.charAt(i + 1) === '(') {
          const end = closingParen(src, i + 2)
          scan(src.slice(i + 2, end))
          i = end + 1
        } else if (d === '`') {
          const end = closing(src, '`', i + 1)
          scan(src.slice(i + 1, end))
          i = end + 1
        } else {
          word += d
          i++
        }
      }
      i++
    } else if (c === '`') {
      const end = closing(src, '`', i + 1)
      scan(src.slice(i + 1, end))
      isWord = true
      i = end + 1
    } else if (c === '#' && !isWord) {
      while (i < src.length && src.charAt(i) !== '\n') i++
    } else if (c === '<' && n === '<') {
      endWord()
      if (src.charAt(i + 2) === '<') {
        i += 3 // a here-string: its word is data, not a delimiter
      } else {
        const tag = heredocTag(src, i + 2)
        queue.push({ tag: tag.tag, stripTabs: tag.stripTabs, runs: cmd.some(w => SHELLS.has(baseName(w))) })
        i = tag.end
      }
    } else if (c === '\n') {
      endCommand()
      i = skipHeredocs(src, i + 1, queue, scan)
    } else if (c === ';' || c === '&' || c === '|' || c === '(' || c === ')') {
      endCommand()
      i++
    } else if (c === ' ' || c === '\t' || c === '\r' || c === '<' || c === '>') {
      endWord() // a redirection ends a word; its target stays a harmless extra word
      i++
    } else {
      word += c
      isWord = true
      i++
    }
  }
  endCommand()
  return out
}

const hasFlag = (args: readonly string[], long: string, short: string) =>
  args.some(a => a === long || (/^-[A-Za-z]+$/.test(a) && a.includes(short)))

function blockedBy(words: readonly string[], depth: number): string | undefined {
  let i = 0
  for (;;) {
    const word = words[i]
    if (word === undefined) return undefined
    if (isAssignment(word) || KEYWORDS.has(word)) {
      i++
    } else if (WRAPPERS.has(baseName(word))) {
      i++
      while (i < words.length && WRAPPER_ARGS.test(words[i] ?? '')) i++
    } else {
      break
    }
  }
  const name = baseName(words[i] ?? '')
  if (SHELLS.has(name)) {
    const flag = words.findIndex((w, k) => k > i && /^-[A-Za-z]*c[A-Za-z]*$/.test(w))
    const script = flag < 0 ? undefined : words[flag + 1]
    return script === undefined || depth >= MAX_DEPTH ? undefined : blockedIn(script, depth + 1)
  }
  if (name === 'eval') return depth >= MAX_DEPTH ? undefined : blockedIn(words.slice(i + 1).join(' '), depth + 1)
  if (name !== 'git') return undefined

  let j = i + 1
  while (j < words.length && (words[j] ?? '').startsWith('-')) j += GIT_VALUE_OPTIONS.has(words[j] ?? '') ? 2 : 1
  const sub = words[j]
  const args = words.slice(j + 1)
  switch (sub) {
    case 'stash':
    case 'clean':
    case 'commit':
    case 'push':
      return `git ${sub}`
    case 'reset':
      return args.includes('--hard') ? 'git reset --hard' : undefined
    case 'checkout':
      if (args.includes('--')) return 'git checkout --'
      return args.some(a => a === '.' || a === './') ? 'git checkout .' : undefined
    case 'restore':
      return hasFlag(args, '--staged', 'S') && !hasFlag(args, '--worktree', 'W') ? undefined : 'git restore'
    default:
      return undefined
  }
}

function blockedIn(src: string, depth: number): string | undefined {
  for (const words of simpleCommands(src)) {
    const op = blockedBy(words, depth)
    if (op !== undefined) return op
  }
  return undefined
}

/** What a Bash command does that a ratchet agent may not (`git stash`, `--no-verify`, …), if anything. */
export function blockedOp(command: string): string | undefined {
  return blockedIn(command, 0) ?? (NO_VERIFY.test(command) ? '--no-verify' : undefined)
}

function isLive(text: string, now: number) {
  let live: { active?: unknown; updated?: unknown } | null
  try {
    live = JSON.parse(text)
  } catch {
    return false
  }
  const at = typeof live?.updated === 'string' ? Date.parse(live.updated) : NaN
  return live?.active === true && Number.isFinite(at) && now - at < MAX_AGE_MS
}

// Module state: a hot reload drops it, which costs one more read.
let cache: { at: number; live: boolean } | undefined

async function runIsLive($: $) {
  const now = await $.clock.now()
  const age = cache ? now - cache.at : -1
  if (cache && age >= 0 && age < CACHE_MS) return cache.live
  const text = await $.fs.read(LIVE_FILE).catch(() => '') // no file: no run
  cache = { at: now, live: isLive(text, now) }
  return cache.live
}

export const register: Register = on => {
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    if (!e.agentId) return next(e)
    const op = blockedOp(e.command)
    if (op === undefined || !(await runIsLive($))) return next(e)
    return { deny: `ratchet is live, so agents may not use ${op}; RS restore and RS check are the safe path.` }
  })
}
