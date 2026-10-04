export const meta = {
  name: "checkpoint",
  description: "Run one ratchet checkpoint through the spec, build, visual and review gates.",
  phases: [
    { title: "Preflight", detail: "A relay reads the checkpoint state." },
    { title: "B0 spec", detail: "The spec agent writes the tests. The b0 gate checks them." },
    { title: "B1 build", detail: "The implement agent builds. The b1 and smoke gates check." },
    { title: "B2 visual", detail: "The capture runs. The visual agent judges the differences." },
    { title: "B3 review", detail: "Two reviewers attack the diff. The b3 gate triages." },
  ],
};

// src/build.ts copies the meta literal above to the top of workflows/checkpoint.js, inlines
// engine/decide.ts in front of this body, and appends `return main();`. The imports below
// vanish in that build, so every name they bring in becomes a top-level function there.
import {
  SPEC_ROUNDS,
  absPath,
  archBlocking,
  capExhausted,
  capQuestion,
  checkState,
  classifyImplement,
  clip,
  composeResult,
  evidenceDir,
  gateCommand,
  gateVerdict,
  ids,
  implementModel,
  INVALID_RECAPTURES,
  isInvalidCapture,
  makeNonce,
  parseArgs,
  readySummary,
  sentence,
  skipArch,
  stagesFrom,
  stateCommand,
  stateRounds,
  verifyRelay,
} from "../engine/decide";
import type { Config, Result, Rounds, Status } from "../engine/decide";

// The Workflow runtime injects these globals. They are declared only for the type checker.
declare const args: unknown;
declare function agent(prompt: string, opts?: Record<string, unknown>): Promise<any>;
declare function parallel(thunks: Array<() => Promise<any>>): Promise<any[]>;
declare function phase(title: string): void;
declare function log(message: string): void;

// Must equal the titles in meta.phases. The runtime matches them exactly.
const P = { pre: "Preflight", b0: "B0 spec", b1: "B1 build", b2: "B2 visual", b3: "B3 review" };

const STRINGS = { type: "array", items: { type: "string" } };
const LEVELS = ["high", "medium", "low"];

// Every RS command adds its own fields, so the relay schema names only the shared ones
// and allows the rest. `evidence` is left out: b3-prep returns a list where other gates return a path.
const RELAY_SCHEMA = {
  type: "object",
  additionalProperties: true,
  properties: {
    ok: { type: "boolean" },
    cmd: { type: "string" },
    nonce: { type: ["string", "null"] },
    verdict: { type: "string", enum: ["pass", "fail", "error"] },
    summary: { type: "string" },
  },
  required: ["ok"],
};

const SPEC_SCHEMA = {
  type: "object",
  properties: {
    tests: STRINGS,
    stubs: STRINGS,
    amendments: {
      type: "array",
      items: {
        type: "object",
        properties: { path: { type: "string" }, reason: { type: "string" } },
        required: ["path", "reason"],
      },
    },
    cases: {
      type: "array",
      items: {
        type: "object",
        properties: { name: { type: "string" }, req: { type: "string" }, kind: { type: "string" } },
        required: ["name"],
      },
    },
    note: { type: "string" },
  },
  required: ["tests", "cases"],
};

const IMPLEMENT_SCHEMA = {
  type: "object",
  properties: {
    status: { type: "string", enum: ["DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED", "SPEC_CONFLICT"] },
    summary: { type: "string" },
    files: STRINGS,
    concerns: STRINGS,
    judgmentCalls: STRINGS,
  },
  required: ["status", "summary"],
};

const VISUAL_SCHEMA = {
  type: "object",
  properties: {
    verdict: { type: "string" },
    differences: {
      type: "array",
      items: {
        type: "object",
        properties: {
          id: { type: "string" },
          element: { type: "string" },
          kind: { type: "string", enum: ["position", "size", "color", "missing", "extra", "text", "other"] },
          delta: { type: "object", properties: { px: { type: "number" }, color: { type: "number" } } },
          engine: { type: "boolean" },
          severity: { type: "string", enum: LEVELS },
          fixable: { type: "boolean" },
          location: { type: "string" },
        },
        required: ["id", "kind"],
      },
    },
  },
  required: ["verdict"],
};

const REVIEW_SCHEMA = {
  type: "object",
  properties: {
    role: { type: "string" },
    round: { type: "number" },
    verdict: { type: "string" },
    findings: {
      type: "array",
      items: {
        type: "object",
        properties: {
          id: { type: "string" },
          severity: { type: "string", enum: LEVELS },
          file: { type: "string" },
          line: { type: "number" },
          target: { type: "string", enum: ["code", "tests", "docs"] },
          issue: { type: "string" },
          scenario: { type: "string" },
          fix: { type: "string" },
          rule: { type: "string" },
          proof: {
            type: "object",
            properties: { cmd: { type: "string" }, pattern: { type: "string" } },
            required: ["cmd", "pattern"],
          },
        },
        required: ["id", "severity", "issue"],
      },
    },
    addressed: {
      type: "array",
      items: {
        type: "object",
        properties: { id: { type: "string" }, status: { type: "string" } },
        required: ["id", "status"],
      },
    },
    declined: STRINGS,
  },
  required: ["verdict", "findings"],
};

// What the next implement round must read: a brief, or the findings of a later gate.
type Fix = { label: string; path: string | null; summary: string };

type ReviewInput = {
  patch: string | null;
  delta: string | null;
  previous: string | null;
  tripwire: string | null;
  checks: string[];
  concerns: string;
};

function agentOpts(
  agentType: string,
  label: string,
  phaseTitle: string,
  schema: object,
  model: string | undefined,
): Record<string, unknown> {
  const opts: Record<string, unknown> = { agentType, label, phase: phaseTitle, schema };
  // Without a model the agent keeps its own default.
  if (model) opts.model = model;
  return opts;
}

function relayPrompt(cfg: Config, command: string): string {
  return [
    `Run this one command from ${cfg.repo} and return the JSON object it prints, unchanged.`,
    "Exit codes 1 and 2 are normal. Run nothing else.",
    "",
    command,
  ].join("\n");
}

function specPrompt(cfg: Config, round: number, out: string, retry: { evidence: string | null } | null): string {
  const lines = [`Write the spec for checkpoint ${cfg.cp} of plan ${cfg.slug}.`, `Repo: ${cfg.repo}`, `Round: ${round}`];
  if (retry) {
    lines.push(
      retry.evidence ? `The spec gate failed. Read ${retry.evidence} and fix the spec.` : "The spec gate failed. Fix the spec.",
    );
  }
  lines.push(`Write your JSON output to ${out}.`);
  return lines.join("\n");
}

function implementPrompt(cfg: Config, round: number, spec: string, out: string, fix: Fix | null): string {
  const lines = [
    `Build checkpoint ${cfg.cp} of plan ${cfg.slug}.`,
    `Repo: ${cfg.repo}`,
    `Round: ${round}`,
    `Spec: ${spec}`,
  ];
  if (fix) {
    if (fix.path) lines.push(`${fix.label}: ${fix.path}`);
    if (fix.summary) lines.push(`Last gate result: ${fix.summary}`);
  }
  lines.push(`Write your JSON output to ${out}.`);
  return lines.join("\n");
}

function imageLines(repo: string, images: unknown): string[] {
  if (!Array.isArray(images)) return [];
  return images
    .filter((im) => im && typeof im === "object")
    .map((im) => `- viewport ${im.viewport}: impl ${absPath(repo, String(im.impl))}, ref ${im.ref ? absPath(repo, String(im.ref)) : "none"}`);
}

function visualPrompt(cfg: Config, round: number, images: string[], capture: string | null, out: string): string {
  const lines = [`Judge the capture for checkpoint ${cfg.cp} of plan ${cfg.slug}.`, `Repo: ${cfg.repo}`, `Round: ${round}`];
  if (images.length > 0) lines.push("Images:", ...images);
  if (capture) lines.push(`Capture evidence: ${capture}`);
  lines.push(`Write your JSON output to ${out}.`);
  return lines.join("\n");
}

function reviewPrompt(cfg: Config, role: string, round: number, input: ReviewInput, out: string): string {
  const lines = [
    `Review checkpoint ${cfg.cp} of plan ${cfg.slug} as the ${role} reviewer.`,
    `Repo: ${cfg.repo}`,
    `Round: ${round}`,
  ];
  if (input.patch) lines.push(`Patch: ${input.patch}`);
  if (input.delta) lines.push(`Delta since the last review: ${input.delta}`);
  if (input.previous) lines.push(`Your previous verdict: ${input.previous}`);
  if (input.tripwire) lines.push(`Tripwire output: ${input.tripwire}`);
  if (input.checks.length > 0) lines.push(`Check outputs: ${input.checks.join(", ")}`);
  if (input.concerns) lines.push(`Implementer concerns to check: ${input.concerns}`);
  lines.push(`Write your verdict to ${out}.`);
  return lines.join("\n");
}

async function run(cfg: Config): Promise<Result> {
  const abs = (path: string) => absPath(cfg.repo, path);
  const evRel = (file: string) => `${evidenceDir(cfg.slug, cfg.cp)}/${file}`;
  const evAbs = (file: string) => abs(evRel(file));
  const pathOrNull = (value: unknown) => (typeof value === "string" && value !== "" ? abs(value) : null);

  let epoch = cfg.epoch;
  let rounds: Rounds = { b0: 0, b1: 0, b2: 0, b3: 0 };
  // STATE keeps counting across runs. Caps count only the rounds of this run, so a run that
  // restarts after a human decision gets a fresh allowance and new evidence file names.
  let base: Rounds = { ...rounds };
  let implRound = 0;
  let nonceCount = 0;
  const concerns: string[] = [];
  const evidence: Record<string, string[]> = {};
  const lastReview: Record<string, number | null> = { arch: null, break: null };

  // Stages end the run early by throwing one of these. Anything else thrown is a harness error.
  const stop = (status: Status, summary: string, question: string | null = null) => ({
    stop: true,
    status,
    summary,
    question,
  });

  const finish = (status: Status, summary: string, question: string | null = null): Result => {
    log(`Result: ${status}. ${clip(summary, 200)}`);
    return composeResult({
      status,
      slug: cfg.slug,
      cp: cfg.cp,
      epoch,
      rounds,
      summary,
      question,
      evidence: Object.values(evidence).flat(),
    });
  };

  // The result keeps the newest evidence of each gate.
  const note = (name: string, res: any) => {
    const paths = [res.evidence, res.patch].flat().filter((p) => typeof p === "string" && p !== "");
    if (paths.length > 0) evidence[name] = paths;
  };

  const relay = async (label: string, command: string, nonce: string | null, phaseTitle: string) => {
    const res = await agent(relayPrompt(cfg, command), {
      agentType: "ratchet:relay",
      schema: RELAY_SCHEMA,
      model: cfg.models.relay || "haiku",
      label,
      phase: phaseTitle,
    });
    const check = verifyRelay(res, nonce);
    if (!check.ok) throw stop("harness-error", `Relay ${label} failed. ${check.reason}`);
    return res;
  };

  // A gate that cannot run ends the run. Callers see only pass or fail.
  const gate = async (
    name: string,
    round: number,
    phaseTitle: string,
    opts: { extra?: string[]; tolerate?: (res: any) => boolean } = {},
  ) => {
    nonceCount += 1;
    const nonce = makeNonce(cfg.nonce, nonceCount);
    const command = gateCommand(cfg.rs, name, cfg.slug, cfg.cp, nonce, round, opts.extra || []);
    const res = await relay(`gate ${name} r${round}`, command, nonce, phaseTitle);
    const verdict = gateVerdict(res);
    log(`${name} round ${round}: ${verdict}. ${clip(res.summary, 120)}`);
    note(name, res);
    if (verdict === "error" && !(opts.tolerate && opts.tolerate(res))) {
      throw stop("harness-error", `The ${name} gate could not run. ${sentence(res.summary)}`);
    }
    return { res, pass: verdict === "pass", error: verdict === "error" };
  };

  const preflight = async () => {
    phase(P.pre);
    nonceCount += 1;
    const stateNonce = makeNonce(cfg.nonce, nonceCount);
    const state = await relay("state", stateCommand(cfg.rs, cfg.slug, cfg.cp, stateNonce), stateNonce, P.pre);
    const check = checkState(state, cfg);
    if (!check.ok) throw stop("harness-error", check.reason);
    if (typeof state.epoch === "number") epoch = state.epoch;
    rounds = stateRounds(state);
    base = { ...rounds };
    implRound = rounds.b1;
    log(`State: stage ${state.stage}. Rounds so far: b0 ${rounds.b0}, b1 ${rounds.b1}, b2 ${rounds.b2}, b3 ${rounds.b3}.`);
    return state;
  };

  const stageB0 = async () => {
    phase(P.b0);
    let retry: { evidence: string | null } | null = null;
    for (let n = 1; n <= SPEC_ROUNDS; n++) {
      const r = base.b0 + n;
      const spec = await agent(
        specPrompt(cfg, r, evAbs("0-spec.json"), retry),
        agentOpts("ratchet:spec", `spec r${r}`, P.b0, SPEC_SCHEMA, cfg.models.spec),
      );
      if (!spec) throw stop("harness-error", "The spec agent returned nothing.");
      const g = await gate("b0", r, P.b0);
      rounds.b0 = r;
      if (g.pass) return;
      if (capExhausted(n, SPEC_ROUNDS)) {
        throw stop("blocked", `The spec gate failed after ${n} rounds. ${sentence(g.res.summary)}`);
      }
      retry = { evidence: pathOrNull(g.res.evidence) };
    }
  };

  // Runs implement rounds until the b1 gate and then the smoke gate pass. The B1 stage calls
  // it with no fix. A failed B2 or B3 gate calls it with that gate's findings.
  const buildUntilGreen = async (first: Fix | null, context: string) => {
    phase(P.b1);
    let fix = first;
    for (let n = 1; n <= cfg.caps.b1; n++) {
      implRound += 1;
      const r = implRound;
      // After a human decision the run restarts here. The last failed b1 gate left the brief for this round.
      const resumed: Fix | null =
        n === 1 && r > 1 ? { label: "Brief, if it exists", path: evAbs(`1-brief-r${r}.md`), summary: "" } : null;
      const impl = await agent(
        implementPrompt(cfg, r, evAbs("0-spec.json"), evAbs(`1-impl-r${r}.json`), fix || resumed),
        agentOpts("ratchet:implement", `implement r${r}`, P.b1, IMPLEMENT_SCHEMA, implementModel(r, cfg.models)),
      );
      if (!impl) throw stop("harness-error", "The implement agent returned nothing.");
      note("implement", { evidence: evRel(`1-impl-r${r}.json`) });
      const outcome = classifyImplement(impl);
      if (outcome.action === "error") {
        throw stop("harness-error", `The implement agent returned an unknown status: ${clip(impl.status, 40) || "none"}.`);
      }
      if (outcome.action === "decide") {
        throw stop("needs-decision", `The implementer reported ${impl.status} in round ${r}.`, outcome.question);
      }
      concerns.push(...outcome.concerns);

      let failed: { name: string; res: any } | null = null;
      const b1 = await gate("b1", r, P.b1);
      rounds.b1 = r;
      if (!b1.pass) failed = { name: "b1", res: b1.res };
      else {
        const smoke = await gate("smoke", r, P.b1);
        if (!smoke.pass) failed = { name: "smoke", res: smoke.res };
      }
      if (!failed) return;

      if (capExhausted(n, cfg.caps.b1)) {
        const where = context ? ` This happened while fixing the ${context}.` : "";
        throw stop(
          "needs-decision",
          `The ${failed.name} gate still fails after ${n} rounds.`,
          capQuestion(failed.name, n, `Last result: ${sentence(failed.res.summary)}${where}`),
        );
      }
      fix = { label: "Brief", path: pathOrNull(failed.res.brief || failed.res.evidence), summary: clip(failed.res.summary, 160) };
    }
  };

  const stageB2 = async () => {
    phase(P.b2);
    for (let n = 1; n <= cfg.caps.b2; n++) {
      const r = base.b2 + n;
      rounds.b2 = r;
      let g: { res: any; pass: boolean; error: boolean } | null = null;
      // An INVALID visual verdict means the two captures show different states. Capture again.
      for (let attempt = 0; attempt <= INVALID_RECAPTURES; attempt++) {
        const capture = await gate("b2-capture", r, P.b2);
        // Identical captures and no regression change: nothing for the visual agent to judge.
        if (capture.pass) return;
        const visual = await agent(
          visualPrompt(cfg, r, imageLines(cfg.repo, capture.res.images), pathOrNull(capture.res.evidence), evAbs(`2-visual-r${r}.json`)),
          agentOpts("ratchet:visual", `visual r${r}`, P.b2, VISUAL_SCHEMA, cfg.models.visual),
        );
        if (!visual) throw stop("harness-error", "The visual agent returned nothing.");
        g = await gate("b2", r, P.b2, { tolerate: isInvalidCapture });
        if (!g.error) break;
        if (attempt === INVALID_RECAPTURES) throw stop("harness-error", `The captures stay invalid. ${sentence(g.res.summary)}`);
        log("The captures show different states. Capturing again.");
      }
      if (!g) throw stop("harness-error", "The b2 gate did not run.");
      if (g.pass) return;
      if (capExhausted(n, cfg.caps.b2)) {
        throw stop(
          "needs-decision",
          `The b2 gate still finds blocking visual differences after ${n} rounds.`,
          capQuestion("b2", n, `Last result: ${sentence(g.res.summary)}`),
        );
      }
      await buildUntilGreen(
        { label: "Findings", path: evAbs(`2-visual-r${r}.json`), summary: clip(g.res.summary, 160) },
        "B2 visual findings",
      );
      phase(P.b2);
    }
  };

  const stageB3 = async () => {
    phase(P.b3);
    // The arch reviewer can only be skipped when it has no open blocking finding to confirm.
    let openArch = 0;
    for (let n = 1; n <= cfg.caps.b3; n++) {
      const r = base.b3 + n;
      rounds.b3 = r;
      const prep = await gate("b3-prep", r, P.b3);
      if (!prep.pass) throw stop("harness-error", `The b3-prep gate did not pass. ${sentence(prep.res.summary)}`);

      const roles = skipArch(r, prep.res.structural, openArch) ? ["break"] : ["arch", "break"];
      if (roles.length === 1) log("The delta is not structural. Skipping the arch reviewer.");
      const common = {
        patch: pathOrNull(prep.res.patch),
        delta: r >= 2 ? pathOrNull(prep.res.delta) : null,
        tripwire: pathOrNull(prep.res.tripwire),
        checks: [prep.res.checkOutputs].flat().filter((p) => typeof p === "string" && p !== "").map(abs),
        concerns: clip(concerns.join("; "), 600),
      };
      const outs = await parallel(
        roles.map((role) => () =>
          agent(
            reviewPrompt(
              cfg,
              role,
              r,
              // A skipped arch reviewer leaves its verdict in an older round.
              { ...common, previous: r >= 2 ? evAbs(`3-${role}-r${lastReview[role] ?? r - 1}.json`) : null },
              evAbs(`3-${role}-r${r}.json`),
            ),
            agentOpts(
              role === "arch" ? "ratchet:review-arch" : "ratchet:review-break",
              `${role} review r${r}`,
              P.b3,
              REVIEW_SCHEMA,
              role === "arch" ? cfg.models.reviewArch : cfg.models.reviewBreak,
            ),
          ),
        ),
      );
      roles.forEach((role, i) => {
        if (!outs[i]) throw stop("harness-error", `The ${role} reviewer returned nothing.`);
        lastReview[role] = r;
      });

      const g = await gate("b3", r, P.b3, { extra: roles.includes("arch") ? [] : ["--skip-arch"] });
      openArch = archBlocking(g.res.blocking);
      if (g.pass) return;
      if (capExhausted(n, cfg.caps.b3)) {
        const notAddressed = ids(g.res.notAddressed);
        const open = notAddressed.length > 0 ? notAddressed : ids(g.res.blocking);
        const detail = open.length > 0 ? `Not addressed: ${open.join(", ")}.` : `Last result: ${sentence(g.res.summary)}`;
        throw stop(
          "needs-decision",
          `The b3 review still has blocking findings after ${n} rounds.`,
          capQuestion("b3", n, detail),
        );
      }
      await buildUntilGreen(
        { label: "Findings", path: evAbs(`3-triage-r${r}.json`), summary: clip(g.res.summary, 160) },
        "B3 review findings",
      );
      phase(P.b3);
    }
  };

  const runners: Record<string, () => Promise<void>> = {
    B0: stageB0,
    B1: () => buildUntilGreen(null, ""),
    B2: stageB2,
    B3: stageB3,
  };

  log(`Checkpoint ${cfg.cp} of plan ${cfg.slug}. Mode: ${cfg.mode || "none"}.`);
  try {
    const state = await preflight();
    const stages = stagesFrom(state.stage, state.visual === true);
    if (stages === null) {
      throw stop("harness-error", `Stage ${clip(state.stage, 20) || "unknown"} is past the engine.`);
    }
    log(`Stages to run: ${stages.length > 0 ? stages.join(", ") : "none"}.`);
    for (const stage of stages) await runners[stage]();
    return finish("ready-for-B4", stages.length > 0 ? readySummary(rounds, concerns) : "The checkpoint already passed B3.");
  } catch (e) {
    const err = e as any;
    if (err && err.stop === true) return finish(err.status, err.summary, err.question);
    return finish("harness-error", `The engine stopped on an error. ${sentence(err && err.message ? err.message : err)}`);
  }
}

async function main(): Promise<Result> {
  const parsed = parseArgs(args);
  if (!parsed.ok) {
    log(`The args are not usable. ${parsed.reason}`);
    return composeResult({
      status: "harness-error",
      slug: null,
      cp: null,
      epoch: null,
      rounds: null,
      summary: `The args are not usable. ${parsed.reason}`,
    });
  }
  return run(parsed.config);
}
