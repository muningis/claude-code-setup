import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { OUT, buildSource } from "../src/build";

// The Workflow runtime runs a script as the body of an async function. The dry run does the same
// with fake globals, so the built file is tested as it ships.
const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;

type Body = Record<string, unknown>;
type Call = {
  type: string;
  name: string;
  nonce: string | null;
  round: number | null;
  prompt: string;
  opts: Record<string, any>;
};
type Reply = Body | null | ((call: Call) => Body | null);
type Script = { state: Reply; gates?: Record<string, Reply>; agents?: Record<string, Reply>; wait?: Reply };

const ARGS = {
  repo: "/repo",
  slug: "s",
  cp: "cp2",
  epoch: 3,
  nonce: "n1",
  rs: "bash /plugin/ratchet.sh",
  mode: "interactive",
  caps: { b1: 5, b2: 3, b3: 3 },
  models: {},
};

const EV = ".claude/ratchet/evidence/s/cp2";

function builtText(): string {
  if (!existsSync(OUT)) throw new Error("workflows/checkpoint.js is missing. Run `bun run build` first.");
  return readFileSync(OUT, "utf8");
}

function parseMeta(text: string): { phases: { title: string }[] } {
  const literal = text.match(/^export const meta = (\{[\s\S]*?\n\});\n/m);
  if (!literal) throw new Error("The built file does not start with the meta literal.");
  return new Function(`return (${literal[1]})`)();
}

// The Workflow runtime keeps only the properties that a schema declares, at every level, even
// with additionalProperties: true. The fake does the same, so a field that the engine reads
// but no schema declares goes missing here as it does in a live run.
function strip(schema: any, value: any): any {
  if (!schema || value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return schema.items ? value.map((v) => strip(schema.items, v)) : value;
  if (!schema.properties) return value;
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(schema.properties)) {
    if (key in value) out[key] = strip(schema.properties[key], value[key]);
  }
  return out;
}

// Scripts the replies of the relay (by command) and of the other agents (by agentType).
// An unscripted call throws, which the engine reports as a harness error.
async function dryRun(script: Script, args: Record<string, any> = ARGS) {
  const calls: Call[] = [];
  const phases: string[] = [];
  const reply = (r: Reply | undefined, call: Call): Body | null => {
    if (r === undefined) throw new Error(`Unscripted call: ${call.name}`);
    return typeof r === "function" ? r(call) : r;
  };

  const agent = async (prompt: string, opts: Record<string, any> = {}) => {
    const call: Call = { type: opts.agentType, name: opts.agentType, nonce: null, round: null, prompt, opts };
    if (opts.agentType !== "ratchet:relay") {
      calls.push(call);
      return strip(opts.schema, reply(script.agents?.[opts.agentType], call));
    }
    const line = prompt.split("\n").find((l) => l.startsWith(args.rs));
    const words = line!.slice(args.rs.length).trim().split(/\s+/);
    const gate = words[0] === "gate" ? words[1] : null;
    call.name = gate ? `gate ${gate}` : words[0];
    if (words.includes("--nonce")) call.nonce = words[words.indexOf("--nonce") + 1];
    if (words.includes("--round")) call.round = Number(words[words.indexOf("--round") + 1]);
    calls.push(call);
    const source = gate ? script.gates?.[gate] : words[0] === "wait" ? script.wait : script.state;
    const body = reply(source, call);
    if (body === null) return null;
    const printed = { ok: true, cmd: call.name, nonce: call.nonce, verdict: "pass", summary: "", ...body };
    // A script can give the relay's text itself. Else the relay copies what RS printed, and a
    // relay that also returns the fields loses them to the runtime.
    const raw = typeof body.raw === "string" ? body.raw : JSON.stringify(printed);
    return strip(opts.schema, { ...printed, raw });
  };
  const parallel = (thunks: Array<() => Promise<unknown>>) => Promise.all(thunks.map((t) => t().catch(() => null)));

  const script_ = builtText().replace(/^export const meta/, "const meta");
  const run = new AsyncFunction("agent", "parallel", "phase", "log", "args", script_);
  const result = await run(agent, parallel, (title: string) => void phases.push(title), () => {}, args);
  return { result, calls, phases };
}

// Replies in order. The last one repeats.
function seq(...replies: Body[]): Reply {
  let i = 0;
  return () => replies[Math.min(i++, replies.length - 1)];
}

const stateAt = (stage: string, extra: Body = {}): Body => ({
  slug: "s",
  cp: "cp2",
  stage,
  epoch: 3,
  visual: false,
  rounds: { b0: 0, b1: 0, b2: 0, b3: 0 },
  ...extra,
});

const IMPL_OK = { status: "DONE", summary: "built", files: ["src/x.ts"], concerns: [], judgmentCalls: [] };
const SPEC_OK = {
  tests: ["src/x.test.ts"],
  stubs: ["src/x.ts"],
  cases: [{ name: "FR-001 rejects an empty title", req: "FR-001", kind: "test" }],
};
const review = (role: string): Body => ({ role, round: 1, verdict: "APPROVE", findings: [] });

describe("checkpoint workflow", () => {
  test("a green run reaches ready-for-B4", async () => {
    const { result, calls, phases } = await dryRun({
      state: stateAt("B0"),
      gates: {
        "b0-prep": { summary: "base abc1234 (new); baseline clean", evidence: `${EV}/0-baseline.txt` },
        b0: { summary: "6 cases", evidence: `${EV}/0-gate.txt` },
        b1: { summary: "12 checks pass", evidence: `${EV}/1-behavior-r1.txt` },
        smoke: { summary: "no smoke checks" },
        "b3-prep": {
          patch: `${EV}/3-patch-r1.diff`,
          evidence: `${EV}/3-patch-r1.diff`,
          delta: null,
          tripwire: `${EV}/3-tripwire-r1.txt`,
          checkOutputs: [`${EV}/3-types-r1.txt`],
          structural: true,
        },
        b3: { summary: "no blocking findings", evidence: `${EV}/3-triage-r1.json` },
      },
      agents: {
        "ratchet:spec": SPEC_OK,
        "ratchet:implement": IMPL_OK,
        "ratchet:review-arch": review("arch"),
        "ratchet:review-break": review("break"),
      },
    });

    expect(result).toEqual({
      status: "ready-for-B4",
      slug: "s",
      cp: "cp2",
      epoch: 3,
      rounds: { b0: 1, b1: 1, b2: 0, b3: 1 },
      summary: "All gates through B3 pass. Rounds: b1 1, b2 0, b3 1.",
      question: null,
      evidence: [
        `${EV}/0-baseline.txt`,
        `${EV}/0-gate.txt`,
        `${EV}/1-impl-r1.json`,
        `${EV}/1-behavior-r1.txt`,
        `${EV}/3-patch-r1.diff`,
        `${EV}/3-triage-r1.json`,
      ],
    });
    expect(calls.map((c) => c.name)).toEqual([
      "state",
      "gate b0-prep",
      "ratchet:spec",
      "gate b0",
      "ratchet:implement",
      "gate b1",
      "gate smoke",
      "gate b3-prep",
      "ratchet:review-arch",
      "ratchet:review-break",
      "gate b3",
    ]);
    expect(calls.filter((c) => c.nonce).map((c) => c.nonce)).toEqual(["n1-1", "n1-2", "n1-3", "n1-4", "n1-5", "n1-6", "n1-7"]);
    // The reviewers get the check outputs of b3-prep, not its patch twice.
    const arch = calls.find((c) => c.type === "ratchet:review-arch");
    expect(arch?.prompt).toContain(`/repo/${EV}/3-types-r1.txt`);
    expect(calls.filter((c) => c.type === "ratchet:relay").every((c) => c.opts.model === "haiku")).toBe(true);

    const titles = parseMeta(builtText()).phases.map((p) => p.title);
    expect(phases).toEqual(["Preflight", "B0 spec", "B1 build", "B3 review"]);
    expect(calls.every((c) => titles.includes(c.opts.phase))).toBe(true);
  });

  test("the b2 gate carries the visual agent's verdict as --verdict-b64", async () => {
    const verdict = { verdict: "FAIL", differences: [{ id: "cp2-V1-1", kind: "text", element: "ünï — title" }] };
    const { calls } = await dryRun({
      state: stateAt("B2", { visual: true }),
      gates: {
        "b2-capture": { verdict: "fail", summary: "images differ", images: [], evidence: `${EV}/2-capture-r1.json` },
        b2: { summary: "no blocking differences", evidence: `${EV}/2-triage-r1.json` },
        "b3-prep": { patch: `${EV}/3-patch-r1.diff`, evidence: `${EV}/3-patch-r1.diff`, checkOutputs: [], structural: true },
        b3: { summary: "no blocking findings", evidence: `${EV}/3-triage-r1.json` },
      },
      agents: { "ratchet:visual": verdict, "ratchet:review-arch": review("arch"), "ratchet:review-break": review("break") },
    });
    const b2 = calls.find((c) => c.name === "gate b2");
    const b64 = b2!.prompt.match(/ --verdict-b64 (\S+)/)?.[1];
    expect(b64).toBeDefined();
    expect(JSON.parse(Buffer.from(b64!, "base64").toString("utf8"))).toEqual(verdict);
    // The capture gate runs before the agent and has nothing to carry.
    expect(calls.find((c) => c.name === "gate b2-capture")!.prompt).not.toContain("--verdict-b64");
  });

  test("SPEC_CONFLICT asks for a decision before any gate runs", async () => {
    const { result, calls } = await dryRun({
      state: stateAt("B1"),
      agents: {
        "ratchet:implement": {
          status: "SPEC_CONFLICT",
          summary: "FR-002 contradicts FR-004",
          files: [],
          concerns: [],
          judgmentCalls: [],
        },
      },
    });

    expect(result.status).toBe("needs-decision");
    expect(result.question).toContain("conflict with the pinned spec");
    expect(result.question).toContain("FR-002 contradicts FR-004");
    expect(result.evidence).toEqual([`${EV}/1-impl-r1.json`]);
    expect(calls.map((c) => c.name)).toEqual(["state", "ratchet:implement"]);
  });

  test("B1 never green stops at the cap and escalates the model from round 4", async () => {
    const { result, calls } = await dryRun({
      state: stateAt("B1"),
      gates: {
        b1: (call) => ({ verdict: "fail", summary: "3 checks failing", brief: `${EV}/1-brief-r${call.round! + 1}.md` }),
      },
      agents: { "ratchet:implement": IMPL_OK },
    });

    const impls = calls.filter((c) => c.type === "ratchet:implement");
    expect(impls.map((c) => c.opts.model)).toEqual(["sonnet", "sonnet", "sonnet", "opus", "opus"]);
    // A decision before round 1 leaves a brief there, so round 1 always names the path.
    expect(impls[0].prompt).toContain(`Brief, if it exists: /repo/${EV}/1-brief-r1.md`);
    expect(impls[2].prompt).toContain(`Brief: /repo/${EV}/1-brief-r3.md`);
    expect(calls.filter((c) => c.name === "gate b1")).toHaveLength(5);
    expect(calls.some((c) => c.name === "gate smoke")).toBe(false);
    expect(result.status).toBe("needs-decision");
    expect(result.rounds.b1).toBe(5);
    expect(result.question).toContain("3 checks failing");
  });

  test("a gate that still runs is awaited in steps, and the wait's own nonce is checked", async () => {
    const { result, calls } = await dryRun({
      state: stateAt("B1"),
      gates: {
        b1: { verdict: "pending", job: "b1-r1-n1-2", summary: "started" },
        smoke: { summary: "no smoke checks" },
        "b3-prep": { patch: `${EV}/3-patch-r1.diff`, structural: true },
        b3: { summary: "no blocking findings" },
      },
      wait: seq({ verdict: "pending", job: "b1-r1-n1-2", summary: "still running" }, { verdict: "pass", summary: "12 checks pass" }),
      agents: { "ratchet:implement": IMPL_OK, "ratchet:review-arch": review("arch"), "ratchet:review-break": review("break") },
    });

    expect(result.status).toBe("ready-for-B4");
    const waits = calls.filter((c) => c.name === "wait");
    expect(waits).toHaveLength(2);
    expect(waits[0].prompt).toContain("wait s cp2 b1-r1-n1-2 --nonce n1-3 --timeout 480");
    expect(calls.find((c) => c.name === "gate b1")?.prompt).toContain("--detach");
  });

  test("a relay that answers with the wrong nonce is a harness error", async () => {
    const { result, calls } = await dryRun({
      state: stateAt("B0"),
      gates: { "b0-prep": {}, b0: { nonce: "forged-1" } },
      agents: { "ratchet:spec": SPEC_OK },
    });

    expect(result.status).toBe("harness-error");
    expect(result.summary).toContain("Nonce mismatch");
    expect(calls.map((c) => c.name)).toEqual(["state", "gate b0-prep", "ratchet:spec", "gate b0"]);
  });

  test("a relay text with no JSON object is a harness error; text around the object is fine", async () => {
    const broken = await dryRun({ state: { raw: "bash: ratchet.sh: No such file or directory" } });
    expect(broken.result.status).toBe("harness-error");
    expect(broken.result.summary).toContain("Relay state failed. The relay text holds no JSON object: bash: ratchet.sh");

    const noisy = await dryRun({
      state: (call) => ({ raw: `Output:\n${JSON.stringify({ ok: true, nonce: call.nonce, ...stateAt("B4") })}\nDone.` }),
    });
    expect(noisy.result).toMatchObject({ status: "ready-for-B4", summary: "The checkpoint already passed B3." });
  });

  test("B3 round 2 skips the arch reviewer when the delta is not structural", async () => {
    const { result, calls } = await dryRun({
      state: stateAt("B3"),
      gates: {
        "b3-prep": seq(
          { patch: `${EV}/3-patch-r1.diff`, delta: null, structural: true, evidence: [] },
          { patch: `${EV}/3-patch-r2.diff`, delta: `${EV}/3-delta-r2.diff`, structural: false, evidence: [] },
        ),
        b3: seq(
          { verdict: "fail", summary: "1 blocking", blocking: ["cp2-B1-1"], notAddressed: [] },
          { verdict: "pass", summary: "clean" },
        ),
        b1: { summary: "ok" },
        smoke: { summary: "no smoke checks" },
      },
      agents: {
        "ratchet:implement": IMPL_OK,
        "ratchet:review-arch": review("arch"),
        "ratchet:review-break": review("break"),
      },
    });

    const arch = calls.filter((c) => c.type === "ratchet:review-arch");
    const brk = calls.filter((c) => c.type === "ratchet:review-break");
    expect(arch).toHaveLength(1);
    expect(brk).toHaveLength(2);
    expect(arch[0].prompt).not.toContain("Your previous verdict");
    expect(brk[1].prompt).toContain(`Delta since the last review: /repo/${EV}/3-delta-r2.diff`);
    expect(brk[1].prompt).toContain(`Your previous verdict: /repo/${EV}/3-break-r1.json`);
    expect(brk[1].prompt).toContain(`Write your verdict to /repo/${EV}/3-break-r2.json.`);
    expect(calls.find((c) => c.type === "ratchet:implement")!.prompt).toContain(
      `Findings: /repo/${EV}/3-triage-r1.json`,
    );
    expect(result).toMatchObject({ status: "ready-for-B4", rounds: { b1: 1, b3: 2 } });
  });
});

describe("built file", () => {
  test("is plain script text with the meta literal first and no clock or random calls", () => {
    const text = builtText();
    expect(text.startsWith("export const meta = {")).toBe(true);
    expect(text.match(/^\s*(?:import|export)\s/gm)).toHaveLength(1);
    expect(text).not.toMatch(/Date\.now|Math\.random|new Date\(\s*\)/);
    expect(text).toContain("return main();");
  });

  test("matches what the build produces from the sources", () => {
    expect(builtText()).toBe(buildSource());
  });
});
