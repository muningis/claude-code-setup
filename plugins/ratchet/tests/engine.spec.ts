import { describe, expect, test } from "bun:test";
import {
  capExhausted,
  classifyImplement,
  implementModel,
  makeNonce,
  parseArgs,
  parseRelay,
  resolveCaps,
  skipArch,
  stagesFrom,
  utf8Base64,
  verifyRelay,
} from "../src/engine/decide";

describe("model choice", () => {
  test("rounds 1-3 use the cheap model and round 4 escalates", () => {
    expect([1, 2, 3].map((r) => implementModel(r, {}))).toEqual(["sonnet", "sonnet", "sonnet"]);
    expect([4, 5].map((r) => implementModel(r, {}))).toEqual(["opus", "opus"]);
    const models = { implement: "haiku", implementEscalate: "fable" };
    expect(implementModel(3, models)).toBe("haiku");
    expect(implementModel(4, models)).toBe("fable");
  });
});

describe("caps", () => {
  test("the last allowed round exhausts the cap, and bad caps fall back to the defaults", () => {
    expect(capExhausted(4, 5)).toBe(false);
    expect(capExhausted(5, 5)).toBe(true);
    expect(capExhausted(1, 1)).toBe(true);
    expect(resolveCaps(undefined)).toEqual({ b1: 5, b2: 3, b3: 3 });
    expect(resolveCaps({ b1: 2, b2: 0, b3: "9" })).toEqual({ b1: 2, b2: 3, b3: 3 });
  });
});

describe("implementer status", () => {
  test("DONE continues, DONE_WITH_CONCERNS carries its concerns, three statuses ask a human", () => {
    expect(classifyImplement({ status: "DONE", summary: "ok", concerns: [] })).toMatchObject({
      action: "continue",
      concerns: [],
    });
    const out = classifyImplement({ status: "DONE_WITH_CONCERNS", summary: "ok", concerns: ["flaky timer", " "] });
    expect(out).toMatchObject({ action: "continue", concerns: ["flaky timer"], question: null });

    for (const status of ["NEEDS_CONTEXT", "BLOCKED", "SPEC_CONFLICT"]) {
      const ask = classifyImplement({ status, summary: "FR-002 contradicts FR-004" });
      expect(ask.action).toBe("decide");
      expect(ask.question).toContain("FR-002 contradicts FR-004.");
      expect(ask.question).toContain("Decide how to proceed.");
    }
    expect(classifyImplement({ status: "WEIRD" }).action).toBe("error");
    expect(classifyImplement(null).action).toBe("error");
  });
});

describe("architecture reviewer", () => {
  test("is skipped only from round 2 on, when the delta is known not to be structural and no arch finding is open", () => {
    expect(skipArch(1, false, 0)).toBe(false);
    expect(skipArch(2, false, 0)).toBe(true);
    expect(skipArch(3, false, 0)).toBe(true);
    expect(skipArch(2, true, 0)).toBe(false);
    expect(skipArch(2, undefined, 0)).toBe(false);
    expect(skipArch(2, false, 1)).toBe(false);
  });
});

describe("relay nonce", () => {
  test("a relay result must echo the nonce that was sent", () => {
    const nonce = makeNonce("run7", 3);
    expect(nonce).toBe("run7-3");
    expect(verifyRelay({ ok: true, nonce }, nonce)).toEqual({ ok: true, reason: "" });
    const stale = verifyRelay({ ok: true, nonce: "run7-2" }, nonce);
    expect(stale.ok).toBe(false);
    expect(stale.reason).toContain("Nonce mismatch");
    expect(verifyRelay({ ok: true }, nonce).ok).toBe(false);
    expect(verifyRelay(null, nonce).ok).toBe(false);
    // The state command takes no nonce, so there is nothing to compare.
    expect(verifyRelay({ ok: true, nonce: null }, null).ok).toBe(true);
  });

  test("the relay's text is parsed whole: every field survives, and noise or a second object is handled", () => {
    const state = { ok: true, nonce: "n-1", slug: "s", cp: "cp2", stage: "B1", epoch: 3, rounds: { b1: 2 } };
    expect(parseRelay({ raw: JSON.stringify(state) })).toEqual({ ok: true, value: state });
    expect(parseRelay({ raw: `exit 1\n${JSON.stringify(state)}\n` })).toEqual({ ok: true, value: state });
    // Two objects: the span from the first "{" to the last "}" is not JSON, so the last line wins.
    expect(parseRelay({ raw: `{"ok": false}\n${JSON.stringify(state)}` })).toEqual({ ok: true, value: state });
    expect(parseRelay({ raw: "[1, 2]" }).ok).toBe(false);
    expect(parseRelay({ raw: "" })).toEqual({ ok: false, reason: "The relay returned no text." });
    expect(parseRelay({ ok: true, nonce: "n-1" })).toEqual({ ok: false, reason: "The relay returned no text." });
    expect(parseRelay(null).ok).toBe(false);
  });
});

describe("args", () => {
  const good = { repo: "/repo/", slug: "s", cp: "cp2", epoch: 3, nonce: "n1", rs: "bash /p/ratchet.sh", caps: { b1: 2 } };

  test("accepts object or JSON-string args, and rejects values that are unsafe in a shell command", () => {
    expect(parseArgs(good)).toMatchObject({
      ok: true,
      config: { repo: "/repo", epoch: 3, mode: null, models: {}, caps: { b1: 2, b2: 3, b3: 3 } },
    });
    expect(parseArgs(JSON.stringify(good))).toMatchObject({ ok: true });
    const bad = [{ slug: "s; rm -rf /" }, { cp: "cp 2" }, { nonce: "a$(x)" }, { slug: "../x" }, { repo: "repo" }, { rs: " " }];
    for (const change of bad) expect(parseArgs({ ...good, ...change })).toMatchObject({ ok: false });
    expect(parseArgs(undefined)).toMatchObject({ ok: false });
  });
});

describe("stages", () => {
  test("the stage in STATE picks where the run starts, and B2 runs only for a visual checkpoint", () => {
    expect(stagesFrom("B0", false)).toEqual(["B0", "B1", "B3"]);
    expect(stagesFrom("B0", true)).toEqual(["B0", "B1", "B2", "B3"]);
    expect(stagesFrom("B2", false)).toEqual(["B3"]);
    expect(stagesFrom("B3", true)).toEqual(["B3"]);
    expect(stagesFrom("B4", true)).toEqual([]);
    expect(stagesFrom("B5", true)).toBeNull();
    expect(stagesFrom("done", false)).toBeNull();
    expect(stagesFrom(undefined, false)).toBeNull();
  });
});

describe("utf8Base64", () => {
  test("matches Buffer for ASCII, multi-byte text and every padding length", () => {
    for (const text of ["", "a", "ab", "abc", "abcd", "ünï — title", "日本語", "😀 emoji", '{"verdict":"PASS"}\n']) {
      expect(utf8Base64(text)).toBe(Buffer.from(text, "utf8").toString("base64"));
    }
  });
});
