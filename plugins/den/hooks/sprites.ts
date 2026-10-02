// Pixel art for the den. Every sprite is a palette-coded grid: one character per
// pixel, '.' transparent. Pure data + one parser, so the mod, the tests and the
// PNG preview script share it (no Node, no DOM).

export const PALETTE: Record<string, number> = {
  K: 0x17161a, // near-black: mask, nose, pupils, outlines
  D: 0x4d4b55, // dark fur: ears, tail rings, shading
  G: 0x8f8c99, // fur
  L: 0xc4c1cc, // light fur
  W: 0xf6f5f2, // white: brows, muzzle, eye shine
  P: 0xe89aa6, // pink: inner ear, tongue
  B: 0x6b4529, // wood dark / floor
  b: 0xa06a3c, // wood light
  M: 0xaab3bd, // metal
  m: 0x67707a, // metal dark
  Y: 0xffd23f, // yellow
  O: 0xff8a1f, // orange (Claude's scarf)
  o: 0xc4621a, // orange shade
  R: 0xe5484d, // red
  C: 0x3fa7ff, // blue
  c: 0x1f5fa8, // blue dark
  N: 0x43b581, // green
  V: 0x9b6bff, // violet
  p: 0xf3ead2, // paper
  t: 0xd8c08a, // tan (explorer hat)
}

export type Sprite = { w: number; h: number; px: Int32Array } // -1 = transparent

export function sprite(rows: readonly string[]): Sprite {
  const h = rows.length
  const w = Math.max(...rows.map(r => r.length))
  const px = new Int32Array(w * h).fill(-1)
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      const ch = row[x]!
      if (ch === '.' || ch === ' ') continue
      const c = PALETTE[ch]
      if (c === undefined) throw new Error(`sprite: unknown palette char '${ch}' at ${x},${y}`)
      px[y * w + x] = c
    }
  })
  return { w, h, px }
}

// ── Raccoons ────────────────────────────────────────────────────────────────
// Big (16×14): Claude, the main loop. Front-facing, sitting, ringed tail right.
const BIG_HEAD = [
  '..DD.......DD...',
  '.DWDD.....DDWD..',
  '.DGGGGGDDGGGGD..',
  '.GWWWGGDDGGWWWG.',
  'GKKKKKGGGGKKKKKG',
  'GKWKKKKGGKKKKWKG',
  'LKKKKKWWWWKKKKKL',
  '.LGGGWWWWWWGGGL.',
  '..GGGWWKKWWGGG..',
]
const BIG_BODY = [
  '...GGGWWWWGGG.DD',
  '..DGGGLLLLGGGDGD',
  '.DGGGLLLLLLGGDDG',
  '.DGGLLLLLLLLGGDD',
  '..KKDDDDDDDDKK..',
]

function withRows(base: string[], at: number, rows: string[]): string[] {
  const out = [...base]
  rows.forEach((r, i) => (out[at + i] = r))
  return out
}

const BIG_OPEN = [...BIG_HEAD, ...BIG_BODY]
// Eyes shut: the shine pixels become mask, plus a lid line.
const BIG_SHUT = withRows(BIG_OPEN, 5, ['GKKKKKKGGKKKKKKG'])
// Looking up at you: bigger whites, pupils high.
const BIG_LOOK = withRows(BIG_OPEN, 4, [
  'GKWWKKGGGGKKWWKG',
  'GKWKKKKGGKKKKWKG',
])

export const BIG = {
  open: sprite(BIG_OPEN),
  shut: sprite(BIG_SHUT),
  look: sprite(BIG_LOOK),
}

// Small (10×10): subagents and the ratchet crew.
const SM_OPEN = [
  '.D......D.',
  'DWD....DWD',
  'DGGGDDGGGD',
  'GWWGDDGWWG',
  'KKKKGGKKKK',
  'KWKKGGKKWK',
  'LKKWWWWKKL',
  '.GGWKKWGG.',
  '.DGLLLLGD.',
  '..K.DD.K..',
]
const SM_SHUT = withRows(SM_OPEN, 5, ['KKKKGGKKKK'])
const SM_LOOK = withRows(SM_OPEN, 4, ['KWWKGGKWWK', 'KWKKGGKKWK'])
// Arms up, cheering: paws raised beside the ears.
const SM_CHEER = withRows(SM_OPEN, 0, ['KD......DK', 'DWD....DWD'])

export const SMALL = {
  open: sprite(SM_OPEN),
  shut: sprite(SM_SHUT),
  look: sprite(SM_LOOK),
  cheer: sprite(SM_CHEER),
}

// Minion (7×7): tiny runner, two leg frames.
export const MINION = [
  sprite([
    'D.....D',
    'DGGDGGD',
    'KWKGKWK',
    '.GWKWG.',
    '.DGLGD.',
    '.DGGGD.',
    '.K...K.',
  ]),
  sprite([
    'D.....D',
    'DGGDGGD',
    'KWKGKWK',
    '.GWKWG.',
    '.DGLGD.',
    '.DGGGD.',
    '..K.K..',
  ]),
]

// ── Hats (drawn over the head) ──────────────────────────────────────────────
export const HAT = {
  explorer: sprite(['..tttttt..', '.tBBBBBBt.', 'tttttttttt']), // Explore
  hard: sprite(['...YYYY...', '..YYYYYY..', '.YYYYYYYY.']), // general-purpose, plugin agents
  plan: sprite(['...cccc...', '..CCCCCC..', '.cCCCCCCc.']), // Plan
  scarf: sprite(['OOOOOOOOOOOO', '.oOOOOOOOOo.', '.....OO.....', '.....Oo.....']), // Claude, at the neck
}

// ── Props, by frame ─────────────────────────────────────────────────────────
export const PROP = {
  book: [sprite(['pppKppp', 'ppKKKpp', 'BBBBBBB']), sprite(['ppKpppp', 'pKKKppp', 'BBBBBBB'])],
  laptop: [
    sprite(['.mmmmmm', '.mCCCCm', '.mCcCCm', 'MMMMMMM']),
    sprite(['.mmmmmm', '.mCCcCm', '.mCCCcm', 'MMMMMMM']),
  ],
  hammer: [
    sprite(['mmm..', 'mMm..', '.b...', '.b...', '.b...']),
    sprite(['.....', '.....', 'bbbmm', '...Mm', '...mm']),
  ],
  magnifier: [sprite(['.mm.', 'mCWm', 'mCCm', '.mm.', '...b', '....b']), sprite(['.mm.', 'mWCm', 'mCCm', '.mm.', '...b', '....b'])],
  telescope: [sprite(['....mm', '.bbbMm', 'bbbb..']), sprite(['....mW', '.bbbMm', 'bbbb..'])],
  megaphone: [sprite(['....R', '..RRR', 'mRRRR', '..RRR', '....R']), sprite(['.....', '..RRR', 'mRRRR', '..RRR', '.....'])],
  clipboard: [
    sprite(['.mm..', 'bppp.', 'bKKp.', 'bppp.', 'bKKpY', 'bpppY']),
    sprite(['.mm..', 'bppp.', 'bKKp.', 'bpppY', 'bKKpY', 'bppp.']),
  ],
  camera: [sprite(['.mm..', 'KKKKK', 'KWCWK', 'KKKKK']), sprite(['WYW..', 'KKKKK', 'KWCWK', 'KKKKK'])],
  ruler: [sprite(['YKYKYKY', 'YYYYYYY']), sprite(['...YKYK', '.YKYKYY', 'YYYY...'])],
  crowbar: [
    sprite(['mm...', '.m...', '.m...', '.m...', '.mm..']),
    sprite(['.....', '.....', 'mmmmm', 'm...m', '.....']),
  ],
  wrench: [sprite(['m.m', 'mmm', '.m.', '.m.']), sprite(['...', 'm.m', 'mmm', '.mm'])],
}

// ── Scenery ─────────────────────────────────────────────────────────────────
export const CAN = {
  shut: sprite(['.mmmmmm.', 'MMMMMMMM', '.mMmMmM.', '.mMmMmM.', '.mMmMmM.', '.mMmMmM.', '.mMmMmM.', '..mmmm..']),
  open: sprite(['MMMMMMMM', '..m.....', '.mMmMmM.', '.mMmMmM.', '.mMmMmM.', '.mMmMmM.', '.mMmMmM.', '..mmmm..']),
}

export const GEAR = [
  sprite([
    '....mmm....',
    '....mMm....',
    '...mMMMm...',
    '..mM...Mm..',
    'mmM.....Mmm',
    'mMM..K..MMm',
    'mmM.....Mmm',
    '..mM...Mm..',
    '...mMMMm...',
    '....mMm....',
    '....mmm....',
  ]),
  sprite([
    '.mm.....mm.',
    '.mMm...mMm.',
    '..mmMMMmm..',
    '..mM...Mm..',
    '..M.....M..',
    '..M..K..M..',
    '..M.....M..',
    '..mM...Mm..',
    '..mmMMMmm..',
    '.mMm...mMm.',
    '.mm.....mm.',
  ]),
]

export const ITEM = {
  box: sprite(['bbbb', 'bBBb', 'bbbb']),
  bag: sprite(['.K.', 'DDD', 'DDD']),
  paper: sprite(['ppp', 'pKp']),
  bolt: sprite(['mm', 'Mm']),
}

export const BUBBLE = [sprite(['.W.', '...', '...']), sprite(['.W.W.', '.....', '.....']), sprite(['.W.W.W', '......', '......'])]

export const Z = sprite(['WWW', '.W.', 'WWW'])

// 3×5 pixel font for the beats' signs.
const FONT: Record<string, string[]> = {
  Y: ['W.W', 'W.W', '.W.', '.W.', '.W.'],
  O: ['WWW', 'W.W', 'W.W', 'W.W', 'WWW'],
  U: ['W.W', 'W.W', 'W.W', 'W.W', 'WWW'],
  R: ['WW.', 'W.W', 'WW.', 'W.W', 'W.W'],
  T: ['WWW', '.W.', '.W.', '.W.', '.W.'],
  N: ['W.W', 'WWW', 'WWW', 'W.W', 'W.W'],
  '!': ['.W.', '.W.', '.W.', '...', '.W.'],
  ' ': ['...', '...', '...', '...', '...'],
}

export function text(s: string, color: string): Sprite {
  const rows = ['', '', '', '', '']
  for (const ch of s.toUpperCase()) {
    const g = FONT[ch] ?? FONT[' ']!
    g.forEach((r, i) => (rows[i] += r.replaceAll('W', color) + '.'))
  }
  return sprite(rows.map(r => r.slice(0, -1)))
}
