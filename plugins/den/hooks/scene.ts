// The den's compositor: a model of who is doing what → a pixel buffer → Raster
// cells (two pixels per cell via ▀). Pure and deterministic per (model, frame),
// so tests and the PNG preview see exactly what the pane shows.
import * as S from './sprites'
import type { Sprite } from './sprites'

export type Role = 'spec' | 'implement' | 'visual' | 'review-arch' | 'review-break'
export const ROLES: readonly Role[] = ['spec', 'implement', 'visual', 'review-arch', 'review-break']

export type Look = {
  id: string
  kind: 'main' | 'agent'
  type: string
  role?: Role
  status: 'idle' | 'working' | 'done' | 'failed'
  tool?: string
  verdict?: 'approve' | 'changes' | 'fail'
  bornAt: number
  endedAt?: number
}
export type BeatKind = 'click' | 'tamper' | 'waiting' | 'confetti'
export type Beat = { kind: BeatKind; at: number }
export type SceneModel = {
  mode: 'calm' | 'hyper'
  actors: readonly Look[]
  beats: readonly Beat[]
  now: number
}

/** Scene height in terminal rows per mode; width follows the pane. */
export const ROWS = { calm: 15, hyper: 17 } as const

// How long an agent takes to climb out of the can, and to go back in once done.
export const POP_MS = 1300
export const GONE_MS = 2900

const C = S.PALETTE

class Canvas {
  px: Int32Array
  constructor(public w: number, public h: number) {
    this.px = new Int32Array(w * h).fill(-1)
  }
  dot(x: number, y: number, c: number) {
    x |= 0
    y |= 0
    if (x >= 0 && y >= 0 && x < this.w && y < this.h) this.px[y * this.w + x] = c
  }
  put(s: Sprite, x: number, y: number, opt: { map?: Map<number, number>; clipBelow?: number } = {}) {
    for (let j = 0; j < s.h; j++) {
      if (opt.clipBelow !== undefined && y + j >= opt.clipBelow) break
      for (let i = 0; i < s.w; i++) {
        const c = s.px[j * s.w + i]!
        if (c >= 0) this.dot(x + i, y + j, opt.map?.get(c) ?? c)
      }
    }
  }
  hline(x: number, y: number, n: number, c: number) {
    for (let i = 0; i < n; i++) this.dot(x + i, y, c)
  }
}

/** Deterministic noise in [0, 1) for particles. */
function rnd(a: number, b = 0): number {
  let h = (a * 374761393 + b * 668265263) | 0
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296
}

const beatAge = (m: SceneModel, kind: BeatKind): number | undefined => {
  const b = [...m.beats].reverse().find(x => x.kind === kind)
  return b ? m.now - b.at : undefined
}

export function toolProp(tool?: string): readonly Sprite[] | undefined {
  if (!tool) return undefined
  if (/^(Read|NotebookRead)$/.test(tool)) return S.PROP.book
  if (/^(Edit|Write|MultiEdit|NotebookEdit)$/.test(tool)) return S.PROP.laptop
  if (/^(Bash|PowerShell|Monitor)$/.test(tool)) return S.PROP.hammer
  if (/^(Grep|Glob|LSP|ToolSearch)$/.test(tool)) return S.PROP.magnifier
  if (/^(WebFetch|WebSearch)$/.test(tool)) return S.PROP.telescope
  if (/^(Agent|SendMessage|Workflow|Skill)$/.test(tool)) return S.PROP.megaphone
  return S.PROP.wrench
}

export function hatFor(type: string): Sprite {
  if (type === 'Explore') return S.HAT.explorer
  if (type === 'Plan') return S.HAT.plan
  return S.HAT.hard
}

const ROLE_PROP: Record<Role, readonly Sprite[]> = {
  spec: S.PROP.clipboard,
  implement: S.PROP.hammer,
  visual: S.PROP.camera,
  'review-arch': S.PROP.ruler,
  'review-break': S.PROP.crowbar,
}
export const ROLE_COLOR: Record<Role, number> = {
  spec: C.Y!,
  implement: C.O!,
  visual: C.C!,
  'review-arch': C.V!,
  'review-break': C.R!,
}
const dim = (c: number) => ((c >> 1) & 0x7f7f7f) + 0x101010

const DIM = new Map(Object.values(C).map(c => [c!, dim(c!)] as [number, number]))

const BANG = S.sprite(['R', 'R', 'R', '.', 'R'])
const CHECK = S.sprite(['....N', '...N.', 'N.N..', '.N...'])
const FLASH = new Map<number, number>([
  [C.m!, C.O!],
  [C.M!, C.Y!],
])

function floor(c: Canvas) {
  for (let x = 0; x < c.w; x++) {
    c.dot(x, c.h - 2, C.B!)
    c.dot(x, c.h - 1, x % 3 === 0 ? C.b! : C.B!)
  }
}

// ── Calm: Claude at the desk, subagents climbing out of the trash can ───────
function calm(c: Canvas, m: SceneModel, f: number) {
  const { w: W, h: H } = c
  floor(c)
  const waiting = beatAge(m, 'waiting') !== undefined
  const main = m.actors.find(a => a.kind === 'main')
  const working = main?.status === 'working'

  const mx = 1
  const bob = working ? (f >> 1) % 2 : 0
  const my = H - 2 - 14 + bob
  const blink = f % 23 === 0
  const pose = waiting ? S.BIG.look : working ? (blink ? S.BIG.shut : S.BIG.open) : S.BIG.shut
  c.put(pose, mx, my)
  c.put(S.HAT.scarf, mx + 2, my + 10)
  if (working) {
    const prop = toolProp(main?.tool)
    if (prop) c.put(prop[(f >> 1) % prop.length]!, mx + 12, my + 7)
    else c.put(S.BUBBLE[(f >> 2) % 3]!, mx + 12, my - 1) // thinking
  } else if (!waiting) {
    const rise = (f >> 1) % 6 // a z drifting up while asleep
    c.put(S.Z, mx + 13 + ((f >> 3) % 2), my - rise)
  }

  // The can sits on a shelf at the right. Agents climb out up there, take the two
  // shelf spots first, then hop down to the floor between Claude and the wall.
  const shelfY = H - 2 - 14
  const canX = W - 9
  const canY = shelfY - 8
  for (let x = 17; x < W; x++) (c.dot(x, shelfY, C.b!), c.dot(x, shelfY + 1, x % 6 === 0 ? C.B! : -1))
  const slots = [
    { x: canX - 11, y: shelfY - 10 },
    { x: canX - 21, y: shelfY - 10 },
    { x: 20, y: H - 2 - 10 },
    { x: 31, y: H - 2 - 10 },
  ].filter(sl => sl.x >= 17 && sl.x + 10 <= W)
  let moving = false
  m.actors
    .filter(a => a.kind === 'agent')
    .slice(0, slots.length)
    .forEach((a, i) => {
      const slot = slots[i]!
      const p = agentPlace(a, m.now, slot.x, slot.y, canX - 1, canY)
      if (!p) return
      moving ||= p.moving
      const sp = p.cheer ? S.SMALL.cheer : a.status === 'working' && (f + i * 7) % 19 === 0 ? S.SMALL.shut : S.SMALL.open
      const clip = p.inCan ? canY + 1 : undefined
      c.put(sp, p.x, p.y, { clipBelow: clip })
      if (!p.cheer) c.put(hatFor(a.type), p.x, p.y - 3, { clipBelow: clip })
      if (!p.moving && a.status === 'working') {
        const prop = toolProp(a.tool) ?? S.PROP.wrench
        c.put(prop[((f >> 1) + i) % prop.length]!, p.x + 6, p.y + 6)
      }
    })
  c.put(moving ? S.CAN.open : S.CAN.shut, canX, canY)
}

/** Where an agent stands: popping out of the can, at its slot, or going back in. */
function agentPlace(a: Look, now: number, slotX: number, slotY: number, canX: number, canY: number) {
  const lerp = (p: number, q: number, u: number) => Math.round(p + (q - p) * u)
  const hop = (u: number) => Math.round(Math.sin(u * Math.PI) * 5)
  if (a.endedAt !== undefined) {
    const t = now - a.endedAt
    if (t < 1600) return { x: slotX, y: slotY - ((t / 200) | 0) % 2, cheer: true, moving: false, inCan: false }
    if (t < 2400) {
      const u = (t - 1600) / 800
      return { x: lerp(slotX, canX, u), y: slotY - hop(u), cheer: false, moving: true, inCan: false }
    }
    if (t < GONE_MS) {
      const u = (t - 2400) / (GONE_MS - 2400)
      return { x: canX, y: lerp(canY - 10, canY + 2, u), cheer: false, moving: true, inCan: true }
    }
    return undefined
  }
  const t = now - a.bornAt
  if (t < 500) return { x: canX, y: lerp(canY + 2, canY - 10, t / 500), cheer: false, moving: true, inCan: true }
  if (t < POP_MS) {
    const u = (t - 500) / (POP_MS - 500)
    return { x: lerp(canX, slotX, u), y: slotY - hop(u), cheer: false, moving: true, inCan: false }
  }
  return { x: slotX, y: slotY, cheer: false, moving: false, inCan: false }
}

// ── Hyper: the ratchet crew at full tilt ────────────────────────────────────

/**
 * Who is on screen in hyper mode: one raccoon per agent actually at work. A crew
 * role shows while its agent works, and for a moment after it ends so its ✓ or !
 * reads; any other working agent (Explore, …) runs the belt as a minion.
 */
export function hyperCast(m: Pick<SceneModel, 'actors' | 'now'>): { crew: Role[]; minions: number } {
  const latest = (role: Role) => [...m.actors].reverse().find(a => a.role === role)
  const crew = ROLES.filter(role => {
    const a = latest(role)
    return a !== undefined && (a.status === 'working' || (a.endedAt !== undefined && m.now - a.endedAt < GONE_MS))
  })
  const minions = m.actors.filter(a => a.kind === 'agent' && !a.role && a.status === 'working').length
  return { crew, minions: Math.min(7, minions) }
}

function hyper(c: Canvas, m: SceneModel, f: number) {
  const { w: W, h: H } = c
  const waiting = beatAge(m, 'waiting') !== undefined
  const F = waiting ? 0 : f // the whole den freezes while it waits on you
  const click = beatAge(m, 'click')
  const clicking = click !== undefined && click < 900
  const jump = clicking ? (((click! / 150) | 0) % 2) * 2 : 0

  // Conveyor belt: rail, moving segments, shadow.
  for (let x = 0; x < W; x++) {
    c.dot(x, H - 3, C.m!)
    c.dot(x, H - 2, (x + F) % 4 < 2 ? C.D! : C.M!)
    c.dot(x, H - 1, C.K!)
  }

  // The crew at their stations, left to right; an empty station keeps its prop.
  const cast = hyperCast(m)
  ROLES.forEach((role, i) => {
    const x = i * 9
    if (!cast.crew.includes(role)) {
      const base = i % 2 ? 7 : 3
      c.hline(x + 1, base + 11, 8, dim(ROLE_COLOR[role]))
      c.put(ROLE_PROP[role][0]!, x + 5, base + 6, { map: DIM })
      return
    }
    const a = [...m.actors].reverse().find(x => x.role === role)
    const status = a?.status ?? 'idle'
    const on = status === 'working'
    const bob = on ? F % 2 : 0
    const y = (i % 2 ? 7 : 3) + bob - jump
    const pose = waiting
      ? S.SMALL.look
      : a?.verdict === 'approve' && !on
        ? S.SMALL.cheer
        : a?.verdict === 'changes' || status === 'failed'
          ? S.SMALL.look
          : (F + i) % 17 === 0
            ? S.SMALL.shut
            : S.SMALL.open
    c.put(pose, x, y)
    c.hline(x + 1, (i % 2 ? 7 : 3) + 11, 8, on ? ROLE_COLOR[role] : dim(ROLE_COLOR[role]))
    const frames = ROLE_PROP[role]
    c.put(frames[on ? F % frames.length : 0]!, x + 5, y + 6)

    if (on && role === 'review-break')
      for (let k = 0; k < 4; k++)
        c.dot(x + 8 + rnd(F, k) * 4, y + 5 + rnd(k, F) * 5, rnd(F + k) < 0.5 ? C.Y! : C.O!)
    if (on && role === 'visual' && F % 8 < 2) {
      for (let d = -2; d <= 2; d++) (c.dot(x + 7 + d, y + 6, C.W!), c.dot(x + 7, y + 6 + d, C.W!))
      c.dot(x + 7, y + 6, C.Y!)
    }
    if (on && role === 'implement' && F % 2 === 1) (c.dot(x + 5, y + 10, C.Y!), c.dot(x + 9, y + 10, C.Y!))
    if (on && role === 'spec') c.dot(x + 4 + (F % 3), y + 10, C.p!)
    if (!waiting && (a?.verdict === 'changes' || status === 'failed')) c.put(BANG, x + 4, y - 5)
    if (!waiting && a?.verdict === 'approve' && !on) c.put(CHECK, x + 3, y - 4)
  })

  // Minions: two lanes running opposite ways, loads on their heads.
  const n = cast.minions
  const items = [S.ITEM.box, S.ITEM.bag, S.ITEM.paper, S.ITEM.bolt]
  for (let k = 0; k < n; k++) {
    const lane = k % 2
    const dir = lane ? -1 : 1
    const speed = 1 + (k % 3)
    const span = W + 16
    const pos = ((F * speed + k * 17) % span) - 8
    const x = dir > 0 ? pos : W - pos - 7
    const y = lane ? H - 3 - 7 : H - 3 - 13
    c.put(S.MINION[(F + k) % 2]!, x, y - jump)
    c.put(items[k % items.length]!, x + 2, y - 3 - jump)
    for (let s = 1; s <= speed; s++) c.dot(x - dir * (1 + s * 2), y + 3, C.D!) // speed lines
    if ((F + k) % 3 === 0) c.dot(x - dir * 2, y + 6, C.L!) // dust
  }

  // Debris flying off the stations in use.
  const used = ROLES.map((r, i) => (cast.crew.includes(r) ? i : -1)).filter(i => i >= 0)
  for (let i = 0; i < (used.length ? 16 : 0); i++) {
    const life = 14 + Math.floor(rnd(i, 1) * 10)
    const t = (F + i * 5) % life
    const sx = used[i % used.length]! * 9 + 5
    const vx = (rnd(i, 2) - 0.5) * 2.4
    const vy = -1.2 - rnd(i, 3) * 1.2
    const px = sx + vx * t
    const py = 10 + vy * t + 0.18 * t * t
    const col = [C.p!, C.m!, C.Y!, C.b!][i % 4]!
    if (py < H - 3) c.dot(px, py, col)
  }

  // The ratchet gear, spinning non-stop; flashes on a lock.
  const gear = S.GEAR[(F >> 0) % 2]!
  c.put(gear, W - 12, H - 3 - 12, { map: clicking ? FLASH : undefined })

  // Beats.
  const tamper = beatAge(m, 'tamper')
  if (tamper !== undefined && tamper < 3000) {
    const on = (F >> 1) % 2 === 0
    for (const sx of [0, W - 2])
      for (let d = 0; d < 2; d++) (c.dot(sx + d, 0, on ? C.R! : C.C!), c.dot(sx + d, 1, on ? C.R! : C.C!))
    if (on) c.hline(0, 0, W, C.R!)
    c.put(BANG, 9 + 4, 0)
  }
  if (waiting) {
    const sign = S.text(W >= 44 ? 'YOUR TURN!' : 'YOU!', 'Y')
    const sx = Math.max(0, ((W - sign.w) >> 1) - 2)
    const sy = 18
    for (let y = sy - 2; y < sy + sign.h + 2; y++)
      for (let x = sx - 2; x < sx + sign.w + 2; x++)
        c.dot(x, y, y === sy - 2 || y === sy + sign.h + 1 || x === sx - 2 || x === sx + sign.w + 1 ? C.b! : C.K!)
    c.put(sign, sx, sy)
  }
  const party = beatAge(m, 'confetti')
  if (party !== undefined && party < 6000) {
    const colors = [C.R!, C.Y!, C.N!, C.C!, C.V!, C.O!]
    for (let i = 0; i < 48; i++) {
      const x = rnd(i, 7) * W
      const y = (rnd(i, 9) * H + f * (1 + (i % 3))) % H
      c.dot(x, y, colors[i % colors.length]!)
    }
  }
}

/** The frame as pixels: `w` columns by `2 * rows` pixel rows. */
export function compose(m: SceneModel, w: number, frame: number): { w: number; h: number; px: Int32Array } {
  const h = ROWS[m.mode] * 2
  const c = new Canvas(w, h)
  if (m.mode === 'hyper') hyper(c, m, frame)
  else calm(c, m, frame)
  return { w, h, px: c.px }
}

const DEFAULT = 0x01000000
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

function base64(bytes: Uint8Array): string {
  let out = ''
  let i = 0
  for (; i + 2 < bytes.length; i += 3) {
    const n = (bytes[i]! << 16) | (bytes[i + 1]! << 8) | bytes[i + 2]!
    out += B64[(n >> 18) & 63]! + B64[(n >> 12) & 63]! + B64[(n >> 6) & 63]! + B64[n & 63]!
  }
  const rest = bytes.length - i
  if (rest === 1) {
    const n = bytes[i]! << 16
    out += B64[(n >> 18) & 63]! + B64[(n >> 12) & 63]! + '=='
  } else if (rest === 2) {
    const n = (bytes[i]! << 16) | (bytes[i + 1]! << 8)
    out += B64[(n >> 18) & 63]! + B64[(n >> 12) & 63]! + B64[(n >> 6) & 63]! + '='
  }
  return out
}

/**
 * Pixels → Raster `cells`: per cell `[codePoint, fg, bg]` as little-endian u32,
 * ▀ with the top pixel as foreground and the bottom one as background; a
 * transparent pixel is the terminal's own color.
 */
export function pack(frame: { w: number; h: number; px: Int32Array }): string {
  const { w, h, px } = frame
  const rows = h >> 1
  const dv = new DataView(new ArrayBuffer(w * rows * 12))
  let o = 0
  const put = (v: number) => (dv.setUint32(o, v >>> 0, true), (o += 4))
  for (let r = 0; r < rows; r++)
    for (let x = 0; x < w; x++) {
      const t = px[2 * r * w + x]!
      const b = px[(2 * r + 1) * w + x]!
      if (t < 0 && b < 0) (put(0x20), put(DEFAULT), put(DEFAULT))
      else if (b < 0) (put(0x2580), put(t), put(DEFAULT))
      else if (t < 0) (put(0x2584), put(b), put(DEFAULT))
      else (put(0x2580), put(t), put(b))
    }
  return base64(new Uint8Array(dv.buffer))
}
