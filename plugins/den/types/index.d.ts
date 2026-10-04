export type DenRole = 'spec' | 'implement' | 'visual' | 'review-arch' | 'review-break'

/** Claude's main loop, or one subagent, as the den draws it. */
export type DenActor = {
  id: string
  kind: 'main' | 'agent'
  /** The agent type (`Explore`, `ratchet:spec`, …); `main` for Claude. */
  type: string
  role?: DenRole
  label: string
  status: 'idle' | 'working' | 'done' | 'failed'
  /** The tool in hand right now, which picks the prop it holds. */
  tool?: string
  activity: string
  verdict?: 'approve' | 'changes' | 'fail'
  bornAt: number
  /** Its last tool call: an agent quiet for long is idle, not working. */
  seenAt?: number
  endedAt?: number
  ms?: number
  tokens?: number
}

export type DenPlanRow = { id: string; title: string; status: string }
export type DenPlan = { slug: string; rows: DenPlanRow[] }
export type DenBeat = { kind: 'click' | 'tamper' | 'waiting' | 'confetti'; at: number }
export type DenMode = 'calm' | 'hyper'

declare module 'claude-code' {
  interface PluginState {
    den: {
      actors: DenActor[]
      mode: DenMode
      plan: DenPlan | null
      ticker: string[]
      beats: DenBeat[]
    }
  }
}
