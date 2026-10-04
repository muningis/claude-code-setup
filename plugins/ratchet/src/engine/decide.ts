// Pure decisions for the checkpoint workflow. src/build.ts inlines this file into
// workflows/checkpoint.js. Keep it free of imports and side effects. Start every
// export with `export function`, `export const` or `export type`, so the build can strip it.

export type Caps = { b1: number; b2: number; b3: number };
export type Rounds = { b0: number; b1: number; b2: number; b3: number };
export type Models = Record<string, string | undefined>;
export type Status = "ready-for-B4" | "needs-decision" | "blocked" | "harness-error";

export type Config = {
  repo: string;
  slug: string;
  cp: string;
  epoch: number | null;
  nonce: string;
  rs: string;
  mode: string | null;
  caps: Caps;
  models: Models;
};

export type Result = {
  status: Status;
  slug: string | null;
  cp: string | null;
  epoch: number | null;
  rounds: Rounds;
  summary: string;
  question: string | null;
  evidence: string[];
};

export const DEFAULT_CAPS: Caps = { b1: 5, b2: 3, b3: 3 };
export const ESCALATE_FROM = 4;
// The spec gets one retry after a failed b0 gate.
export const SPEC_ROUNDS = 2;
export const INVALID_RECAPTURES = 2;

const STAGE_ORDER = ["B0", "B1", "B2", "B3"];
// Slug, cp and nonce go into a shell command that a relay agent runs. This keeps them inert.
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const ABSOLUTE = /^(\/|[A-Za-z]:[\\/])/;

const DECISION_STEMS: Record<string, string> = {
  NEEDS_CONTEXT: "The implementer needs more context.",
  BLOCKED: "The implementer is blocked.",
  SPEC_CONFLICT: "The implementer found a conflict with the pinned spec.",
};

const CAP_STEMS: Record<string, string> = {
  b1: "The b1 gate still fails",
  smoke: "The smoke gate still fails",
  b2: "The b2 gate still finds blocking visual differences",
  b3: "The b3 review still has unaddressed blocking findings",
};

export function clip(text: unknown, max = 160): string {
  const flat = String(text === null || text === undefined ? "" : text).replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 3)}...` : flat;
}

// A clipped text that always ends like a sentence, so it can sit between two sentences.
export function sentence(text: unknown, max = 200): string {
  const flat = clip(text, max);
  return flat && !/[.!?]$/.test(flat) ? `${flat}.` : flat;
}

export function strings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v) => typeof v === "string" && v.trim() !== "").map((v) => v.trim());
}

export function unique(value: unknown): string[] {
  return Array.from(new Set(strings(value)));
}

// Finding IDs from a gate field that holds strings or objects with an `id`.
export function ids(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((v) => (typeof v === "string" ? v : v && typeof v.id === "string" ? v.id : ""))
    .filter((v) => v !== "");
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : 0;
}

// Gate results hold paths relative to the repo root. Agents need absolute paths.
export function absPath(repo: string, path: string): string {
  return ABSOLUTE.test(path) ? path : `${repo}/${path}`;
}

export function evidenceDir(slug: string, cp: string): string {
  return `.claude/ratchet/evidence/${slug}/${cp}`;
}

function isSafeName(value: unknown): boolean {
  return typeof value === "string" && SAFE_NAME.test(value) && !value.includes("..");
}

export function resolveCaps(raw: unknown): Caps {
  const given: Record<string, unknown> = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const pick = (key: keyof Caps): number => {
    const value = given[key];
    return typeof value === "number" && Number.isInteger(value) && value >= 1 ? value : DEFAULT_CAPS[key];
  };
  return { b1: pick("b1"), b2: pick("b2"), b3: pick("b3") };
}

export function parseArgs(raw: unknown): { ok: true; config: Config } | { ok: false; reason: string } {
  let a: any = raw;
  // The Workflow runtime can hand object args over as a JSON string.
  if (typeof a === "string" && a.trimStart().startsWith("{")) {
    try {
      a = JSON.parse(a);
    } catch (e) {
      return { ok: false, reason: "args is not valid JSON." };
    }
  }
  if (!a || typeof a !== "object") return { ok: false, reason: "args must be an object." };
  for (const key of ["slug", "cp", "nonce"]) {
    if (!isSafeName(a[key])) {
      return { ok: false, reason: `args.${key} must use only letters, digits, dot, dash and underscore.` };
    }
  }
  if (typeof a.repo !== "string" || !ABSOLUTE.test(a.repo)) {
    return { ok: false, reason: "args.repo must be an absolute path." };
  }
  if (typeof a.rs !== "string" || a.rs.trim() === "") {
    return { ok: false, reason: "args.rs must be the ratchet.sh command." };
  }
  return {
    ok: true,
    config: {
      repo: a.repo.replace(/[\\/]+$/, ""),
      slug: a.slug,
      cp: a.cp,
      epoch: typeof a.epoch === "number" ? a.epoch : null,
      nonce: a.nonce,
      rs: a.rs.trim(),
      mode: typeof a.mode === "string" ? a.mode : null,
      caps: resolveCaps(a.caps),
      models: a.models && typeof a.models === "object" ? a.models : {},
    },
  };
}

export function implementModel(round: number, models: Models): string {
  return round >= ESCALATE_FROM ? models.implementEscalate || "opus" : models.implement || "sonnet";
}

// `used` counts the rounds of this run that have already failed.
export function capExhausted(used: number, cap: number): boolean {
  return used >= cap;
}

// The stages to run, in order, from the stage in STATE. Null means the engine has nothing to do there.
export function stagesFrom(stage: unknown, visual: boolean): string[] | null {
  if (stage === "B4") return [];
  const at = STAGE_ORDER.indexOf(String(stage));
  if (at < 0) return null;
  return STAGE_ORDER.slice(at).filter((s) => s !== "B2" || visual);
}

export function stateRounds(state: any): Rounds {
  const given = state && state.rounds && typeof state.rounds === "object" ? state.rounds : {};
  return { b0: count(given.b0), b1: count(given.b1), b2: count(given.b2), b3: count(given.b3) };
}

export function checkState(state: any, want: { slug: string; cp: string }): { ok: boolean; reason: string } {
  const bad = (reason: string) => ({ ok: false, reason });
  if (!state || typeof state !== "object") return bad("The state result is empty.");
  if (typeof state.harnessError === "string" && state.harnessError) {
    return bad(`The state command failed. ${sentence(state.harnessError)}`);
  }
  if (state.ok === false || state.verdict === "error") {
    return bad(`The state command failed. ${sentence(state.summary) || "No reason given."}`);
  }
  // The nonce proves that the relay answered this call; this proves that the answer is for this checkpoint.
  if (state.slug !== want.slug || state.cp !== want.cp) {
    return bad(`The state is for ${clip(state.slug, 40)}/${clip(state.cp, 40)}, not ${want.slug}/${want.cp}.`);
  }
  return { ok: true, reason: "" };
}

export function stateCommand(rs: string, slug: string, cp: string, nonce: string): string {
  return `${rs} state ${slug} ${cp} --nonce ${nonce}`;
}

export function gateCommand(
  rs: string,
  gate: string,
  slug: string,
  cp: string,
  nonce: string,
  round: number | null,
  extra: string[] = [],
): string {
  const flag = round === null ? "" : ` --round ${round}`;
  const more = extra.length > 0 ? ` ${extra.join(" ")}` : "";
  return `${rs} gate ${gate} ${slug} ${cp} --nonce ${nonce}${flag}${more}`;
}

// Deterministic on purpose. The runtime forbids clock and random calls, and a resume
// replays cached relay results only when the prompts are identical. Pass a new base
// nonce for each run that must execute its gates again.
export function makeNonce(base: string, counter: number): string {
  return `${base}-${counter}`;
}

// A nonce check proves that the relay answered this command. It cannot prove that the relay ran it.
// The Workflow runtime keeps only the properties that an agent's schema declares, and every
// RS command prints fields of its own. So the relay hands back the printed text, and the
// engine parses it here: the object from the first "{" to the last "}", or else the last
// line that is an object (when the text holds two).
export function parseRelay(wrapped: unknown): { ok: true; value: any } | { ok: false; reason: string } {
  const raw = wrapped && typeof wrapped === "object" ? (wrapped as { raw?: unknown }).raw : undefined;
  if (typeof raw !== "string" || raw.trim() === "") return { ok: false, reason: "The relay returned no text." };
  const asObject = (text: string) => {
    try {
      const value = JSON.parse(text);
      return value && typeof value === "object" && !Array.isArray(value) ? value : null;
    } catch {
      return null;
    }
  };
  const first = raw.indexOf("{");
  const last = raw.lastIndexOf("}");
  const whole = first >= 0 && last > first ? asObject(raw.slice(first, last + 1)) : null;
  if (whole) return { ok: true, value: whole };
  const lines = raw.split("\n").map((l) => l.trim()).filter((l) => l.startsWith("{")).reverse();
  for (const line of lines) {
    const value = asObject(line);
    if (value) return { ok: true, value };
  }
  return { ok: false, reason: `The relay text holds no JSON object: ${clip(raw, 160)}` };
}

export function verifyRelay(res: any, nonce: string | null): { ok: boolean; reason: string } {
  if (!res || typeof res !== "object" || Array.isArray(res)) {
    return { ok: false, reason: "The relay returned no result." };
  }
  if (nonce !== null && res.nonce !== nonce) {
    const got = JSON.stringify(res.nonce === undefined ? null : res.nonce);
    return { ok: false, reason: `Nonce mismatch. Sent ${nonce}, got ${got}.` };
  }
  return { ok: true, reason: "" };
}

export function gateVerdict(res: any): "pass" | "fail" | "error" | "pending" {
  const v = res && res.verdict;
  return v === "pass" || v === "fail" || v === "pending" ? v : "error";
}

// A relay's Bash call stops after 10 minutes, and a gate can run longer (a full build and
// suite). So each gate runs detached, and the engine waits in steps below that limit.
export const WAIT_SECONDS = 480;
export const MAX_WAITS = 15;

export function waitCommand(rs: string, slug: string, cp: string, job: string, nonce: string): string {
  return `${rs} wait ${slug} ${cp} ${job} --nonce ${nonce} --timeout ${WAIT_SECONDS}`;
}

// The job ID comes back from a relay and goes into the next shell command.
export function isSafeJob(job: unknown): job is string {
  return typeof job === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(job) && !job.includes("..");
}

export function classifyImplement(impl: any): {
  action: "continue" | "decide" | "error";
  concerns: string[];
  question: string | null;
} {
  const status = impl && typeof impl === "object" ? impl.status : undefined;
  const concerns = strings(impl && impl.concerns);
  if (status === "DONE" || status === "DONE_WITH_CONCERNS") {
    return { action: "continue", concerns, question: null };
  }
  if (typeof status === "string" && Object.prototype.hasOwnProperty.call(DECISION_STEMS, status)) {
    const parts = [DECISION_STEMS[status], sentence(impl.summary, 300)];
    if (concerns.length > 0) parts.push(`Concerns: ${concerns.join("; ")}.`);
    parts.push("Decide how to proceed.");
    return { action: "decide", concerns, question: parts.filter((p) => p !== "").join(" ") };
  }
  return { action: "error", concerns: [], question: null };
}

// A missing `structural` flag is not `false`, so an unknown delta still gets the arch review.
// An open blocking arch finding needs the arch reviewer to confirm the fix, so it also forces a review.
export function skipArch(round: number, structural: unknown, openArchBlocking: number): boolean {
  return round >= 2 && structural === false && openArchBlocking === 0;
}

// Finding IDs are `<cp>-<A|B|V><round>-<n>`, so the letter after the dash names the reviewer.
export function archBlocking(blocking: unknown): number {
  return ids(blocking).filter((id) => /-A\d+-\d+$/.test(id)).length;
}

// The b2 gate reports an INVALID visual verdict as an error whose summary starts this way.
export function isInvalidCapture(res: any): boolean {
  return gateVerdict(res) === "error" && typeof res?.summary === "string" && /^invalid capture/i.test(res.summary);
}

export function capQuestion(gate: string, rounds: number, detail: string): string {
  const stem = CAP_STEMS[gate] || `The ${gate} gate still fails`;
  const unit = rounds === 1 ? "round" : "rounds";
  return `${stem} after ${rounds} ${unit}. ${detail} Decide whether to continue, change the plan, or stop.`;
}

export function readySummary(rounds: Rounds, concerns: string[]): string {
  const base = `All gates through B3 pass. Rounds: b1 ${rounds.b1}, b2 ${rounds.b2}, b3 ${rounds.b3}.`;
  return concerns.length > 0 ? `${base} Implementer concerns: ${sentence(concerns.join("; "), 400)}` : base;
}

export function composeResult(p: {
  status: Status;
  slug: string | null;
  cp: string | null;
  epoch: number | null;
  rounds: Partial<Rounds> | null;
  summary: string;
  question?: string | null;
  evidence?: unknown;
}): Result {
  const rounds: Partial<Rounds> = p.rounds || {};
  return {
    status: p.status,
    slug: p.slug,
    cp: p.cp,
    epoch: p.epoch,
    rounds: { b0: count(rounds.b0), b1: count(rounds.b1), b2: count(rounds.b2), b3: count(rounds.b3) },
    summary: p.summary,
    question: p.status === "needs-decision" ? p.question || p.summary : null,
    evidence: unique(p.evidence),
  };
}
