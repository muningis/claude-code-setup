import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const PY = process.env.RATCHET_TEST_PYTHON || "python3";
const RS = resolve(import.meta.dir, "../skills/ratchet/scripts/rs");
const STELINT = join(RS, "cmd_stelint.py");
const DOCLINT = join(RS, "cmd_doclint.py");
const FIX = join(import.meta.dir, "fixtures/docs");

type Finding = { path: string; line: number; severity: string; rule: string; message: string };
type Run = { code: number; out: any; stdout: string; stderr: string; findings: Finding[]; evidence: string };

let scratch = "";
let seq = 0;

beforeAll(() => {
  // Scratch lives under the fixtures folder. The lock file is always passed in, so no run touches a repo lock.
  scratch = mkdtempSync(join(FIX, ".scratch-"));
});
afterAll(() => rmSync(scratch, { recursive: true, force: true }));

function run(script: string, args: string[], opts: { lock?: string; noOut?: boolean } = {}): Run {
  const evidence = join(scratch, `evidence-${seq++}.json`);
  const full = [PY, script, ...args];
  if (!opts.noOut) full.push("--out", evidence);
  if (script === DOCLINT && !args.includes("--lock-file")) full.push("--lock-file", opts.lock ?? join(scratch, "none.lock"));
  const p = Bun.spawnSync(full, { cwd: scratch, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
  const stdout = p.stdout.toString();
  let out: any = null;
  try {
    out = JSON.parse(stdout);
  } catch {}
  const findings = !opts.noOut && existsSync(evidence) && out ? JSON.parse(readFileSync(evidence, "utf8")).findings ?? [] : [];
  return { code: p.exitCode ?? -1, out, stdout, stderr: p.stderr.toString(), findings, evidence };
}

const ste = (args: string[]) => run(STELINT, args);
const doc = (args: string[], opts?: { lock?: string }) => run(DOCLINT, args, opts);
const blocks = (r: Run) => r.findings.filter((f) => f.severity === "block");
const rules = (r: Run, severity?: string) =>
  r.findings.filter((f) => !severity || f.severity === severity).map((f) => `${f.rule}@${f.line}`);
const fixture = (name: string) => join(FIX, name);

function write(name: string, text: string): string {
  const path = join(scratch, name);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text);
  return path;
}
// A sentence of exactly n words. The filler is made of verbs and function words, so no style rule fires.
const sentence = (n: number) => "Go" + " on".repeat(n - 1) + ".";
const lineOf = (path: string, needle: string) =>
  readFileSync(path, "utf8").split("\n").findIndex((l) => l.includes(needle)) + 1;

describe("stelint", () => {
  test("FR-009 a sentence of 26 words blocks and 25 words passes", () => {
    const ok = ste([write("s25.md", sentence(25) + "\n")]);
    expect(ok.code).toBe(0);
    expect(blocks(ok)).toEqual([]);

    const bad26 = write("s26.md", "First line.\n\n" + sentence(26) + "\n");
    const bad = ste([bad26]);
    expect(bad.code).toBe(1);
    expect(bad.out.verdict).toBe("fail");
    expect(rules(bad, "block")).toEqual(["STE-SENT-LEN@3"]);

    const text = Bun.spawnSync([PY, STELINT, bad26, "--format", "text"], { cwd: scratch });
    expect(text.exitCode).toBe(1);
    expect(text.stdout.toString().split("\n")[0]).toBe(
      `${bad26}:3: block STE-SENT-LEN Sentence has 26 words. Keep it to 25 or fewer.`,
    );
  });

  test("split edge cases do not over-count sentences or words", () => {
    // 6 real sentences with many dots inside them: abbreviations, file names, decimals, versions.
    const edge = ste([fixture("ste/split-edge.md")]);
    expect(edge.code).toBe(0);
    expect(rules(edge, "block")).toEqual([]);

    // The dots must not split a sentence: 26 words block, 25 pass, with the same dots inside.
    const pre = "Use e.g. a.ts and i.e. b.ts and vs. c.ts and 3.5 and v1.2.3 and etc. then";
    const fill = (n: number) => pre + " on".repeat(n - pre.split(" ").length) + ".";
    expect(ste([write("dots25.md", fill(25) + "\n")]).code).toBe(0);
    expect(rules(ste([write("dots26.md", fill(26) + "\n")]), "block")).toEqual(["STE-SENT-LEN@1"]);

    // Real sentence ends after a file name, a decimal or a version still split: 7 sentences block.
    const seven = "Use a.ts first. Then run b.ts. Next read c.md. After that, e.g. d.md, edit it. Then test v1.2.3. Then ship 3.5 units. Then stop.\n";
    expect(rules(ste([write("seven.md", seven)]), "block")).toEqual(["STE-PARA-LEN@1"]);
  });

  test("a procedure step of 21 words blocks by list, heading and marker, and a plain paragraph does not", () => {
    const s21 = sentence(21);
    const lines = [
      "# Guide", "", `1. ${s21}`, `2. ${sentence(20)}`, "",
      "## Install", "", `- ${s21}`, "",
      "## Installation notes", "", `- ${s21}`, "",
      "## How to ship it", "", `- ${s21}`, "",
      "## Notes", "", "<!-- ste: procedural -->", s21, "", s21, "",
    ];
    const r = ste([write("steps.md", lines.join("\n"))]);
    expect(r.code).toBe(1);
    // Numbered item, whole-word "Install", "How to"; not "Installation"; the marker covers one paragraph.
    expect(rules(r, "block")).toEqual(["STE-STEP-LEN@3", "STE-STEP-LEN@8", "STE-STEP-LEN@16", "STE-STEP-LEN@21"]);
  });

  test("masked code, URL, table, comment, heading and front matter do not count, and inline code counts as one word", () => {
    const masked = ste([fixture("ste/masked.md")]);
    expect(masked.code).toBe(0);
    expect(masked.findings).toEqual([]);

    // 23 words around one inline code span of 5 words is 25 words: pass. One more word is 26: block.
    const inline = (n: number) => "Go" + " on".repeat(n - 2) + " `a b c d e`.";
    expect(ste([write("inline25.md", inline(25) + "\n")]).code).toBe(0);
    expect(rules(ste([write("inline26.md", inline(26) + "\n")]), "block")).toEqual(["STE-SENT-LEN@1"]);
  });

  test("passive and progressive warn, an allowlisted adjective does not, and warnings keep exit 0", () => {
    const r = ste([fixture("ste/voice.md")]);
    expect(r.code).toBe(0);
    expect(rules(r)).toEqual(["STE-PASSIVE@1", "STE-PROGRESSIVE@3"]);
    expect(r.findings.every((f) => f.severity === "warn")).toBe(true);
    // Lines 5 and 7 hold "is based on" and "is done": adjectival participles stay quiet.
    expect(r.findings.some((f) => f.line > 3)).toBe(false);
  });

  test("mode full turns style warnings into blocks but keeps noun clusters as warnings, and mode off passes", () => {
    const full = ste([fixture("ste/voice.md"), "--mode", "full"]);
    expect(full.code).toBe(1);
    expect(rules(full, "block")).toEqual(["STE-PASSIVE@1", "STE-PROGRESSIVE@3"]);

    const cluster = ste([fixture("ste/cluster.md"), "--mode", "full"]);
    expect(cluster.code).toBe(0);
    expect(rules(cluster, "warn")).toEqual(["STE-NOUN-CLUSTER@1"]);

    const long = write("long.md", sentence(40) + "\n");
    expect(ste([long]).code).toBe(1);
    const off = ste([long, "--mode", "off"]);
    expect(off.code).toBe(0);
    expect(off.out.summary).toBe("off");
    expect(off.out.verdict).toBe("pass");
  });
});

describe("doclint", () => {
  test("design log sections out of order block", () => {
    const r = doc([fixture("bad/order.md")]);
    expect(r.code).toBe(1);
    expect(rules(r, "block")).toEqual(["DOC-SECTION-ORDER@26"]);
    expect(r.findings[0].message).toContain("'Questions and answers' must come before 'Design'");
    expect(doc([fixture("valid/design-log.md"), "--approval"]).code).toBe(0);
  });

  test("an open question blocks only with --approval", () => {
    const path = fixture("bad/open-question.md");
    const draft = doc([path]);
    expect(draft.code).toBe(0);
    expect(draft.findings).toEqual([]);

    const approval = doc([path, "--approval"]);
    expect(approval.code).toBe(1);
    // Q2 `A: OPEN`, Q4 has no A line, Q5 `A: open: ...`. Q3 only has "Open" on a later line, so it is answered.
    expect(rules(approval, "block")).toEqual(
      ["Q2:", "Q4:", "Q5:"].map((q) => `DOC-QA-OPEN@${lineOf(path, q)}`),
    );
  });

  test("EARS: two shall, a bad pattern and a missing kind block, and all seven patterns pass", () => {
    const path = fixture("bad/ears.md");
    const r = doc([path]);
    expect(r.code).toBe(1);
    expect(rules(r, "block")).toEqual([
      `DOC-REQ-SHALL@${lineOf(path, "FR-002")}`,
      `DOC-REQ-EARS@${lineOf(path, "FR-003")}`,
      `DOC-REQ-KIND@${lineOf(path, "FR-004")}`,
    ]);
    const ok = doc([fixture("valid/patterns.md")]);
    expect(ok.code).toBe(0);
    expect(ok.findings).toEqual([]);
  });

  test("an ADR with one considered option blocks", () => {
    const one = doc([fixture("adr/0001-one-option.md")]);
    expect(one.code).toBe(1);
    expect(rules(one, "block")).toEqual(["DOC-ADR-OPTIONS@13"]);
    expect(doc([fixture("adr/0002-two-options.md"), "--approval"]).code).toBe(0);
  });

  test("FR-010 an edit inside the approved body blocks, and an append after it passes", () => {
    const file = join(scratch, "lock-a", "design-log.md");
    mkdirSync(dirname(file), { recursive: true });
    copyFileSync(fixture("valid/design-log.md"), file);
    const lock = join(scratch, "lock-a", "docs.lock");

    const approve = doc(["--approve", file], { lock });
    expect(approve.code).toBe(0);
    expect(approve.out.approved).toBeTruthy();
    const records = readFileSync(lock, "utf8").trim().split("\n").map((l) => JSON.parse(l));
    expect(records).toHaveLength(1);
    const raw = readFileSync(file);
    const body = raw.subarray(raw.indexOf("\n---\n", 3) + 5);
    expect(records[0].bytes).toBe(body.length);
    expect(records[0].sha256).toBe(createHash("sha256").update(body).digest("hex"));
    expect(doc([file], { lock }).code).toBe(0);

    const original = raw.toString("utf8");
    writeFileSync(file, original.replace("small image", "tiny image"));
    const edited = doc([file], { lock });
    expect(edited.code).toBe(1);
    expect(rules(edited, "block")).toEqual(["DOC-LOCK@7"]);
    const before = readFileSync(lock, "utf8");
    expect(doc(["--approve", file], { lock }).code).toBe(1); // a new record must not launder the edit
    expect(readFileSync(lock, "utf8")).toBe(before);

    writeFileSync(file, original + "\n## Trade-offs\n\n- The header does not crop the avatar.\n");
    expect(doc([file], { lock }).code).toBe(0);
  });

  test("a front matter status change after approve passes", () => {
    // spec: status approved to done is a front matter edit only.
    const spec = write("lock-b/spec.md", readFileSync(fixture("valid/spec.md"), "utf8"));
    const lockB = join(scratch, "lock-b", "docs.lock");
    expect(doc(["--approve", spec], { lock: lockB }).code).toBe(0);
    writeFileSync(spec, readFileSync(spec, "utf8").replace("status: approved", "status: done"));
    expect(doc([spec], { lock: lockB }).code).toBe(0);

    // design log: done needs a Results section with a dated entry and an X/Y line.
    const logText = readFileSync(fixture("valid/design-log.md"), "utf8").replace("status: draft", "status: approved");
    const log = write("lock-c/design-log.md", logText);
    const lockC = join(scratch, "lock-c", "docs.lock");
    expect(doc(["--approve", log], { lock: lockC }).code).toBe(0);
    const done = logText.replace("status: approved", "status: done");
    writeFileSync(log, done);
    expect(rules(doc([log], { lock: lockC }), "block")).toEqual(["DOC-SECTION-MISSING@7"]);
    const results = "\n## Results\n\n### 2026-10-04 · cp1 header\n- 3/3 requirements verified (FR-001, FR-002, FR-003)\n";
    writeFileSync(log, done + results);
    const after = doc([log], { lock: lockC });
    expect(after.code).toBe(0);
    expect(blocks(after)).toEqual([]);
  });

  test("word budgets warn, and block with --approval; [NEEDS CLARIFICATION] blocks with --approval", () => {
    const prd = (filler: number, outcome = "A result that a test can measure.") =>
      [
        "---", "type: prd", "change: 0007-budget", "status: draft", "---", "",
        "## Problem", "", "word ".repeat(filler).trim() + ".", "",
        "## Outcome", "", outcome, "",
        "## Non-goals", "", "- No new screens.", "",
        "## Scenarios", "", "1. The user opens the page.", "",
        "## Success criteria", "", "- A user finds the avatar in two seconds.", "",
        "## Risks", "", "- The API is slow (medium).", "",
      ].join("\n");
    expect(doc([write("prd-small.md", prd(20)), "--approval"]).code).toBe(0);

    const big = write("prd-big.md", prd(320));
    const warn = doc([big]);
    expect(warn.code).toBe(0);
    expect(rules(warn, "warn")).toEqual(["DOC-BUDGET@1"]);
    const block = doc([big, "--approval"]);
    expect(block.code).toBe(1);
    expect(rules(block, "block")).toEqual(["DOC-BUDGET@1"]);

    const open = write("prd-open.md", prd(20, "The result is [NEEDS CLARIFICATION: which metric?]."));
    expect(doc([open]).code).toBe(0);
    expect(rules(doc([open, "--approval"]), "block")).toEqual([`DOC-CLARIFY@${lineOf(open, "NEEDS CLARIFICATION")}`]);
    const quoted = write("prd-quoted.md", prd(20, "Write `[NEEDS CLARIFICATION]` for an open point."));
    expect(doc([quoted, "--approval"]).code).toBe(0);
  });
});

describe("output contract", () => {
  test("nonce, evidence hash, the 1 KB cap and the exit codes", () => {
    const many = write("many.md", Array.from({ length: 80 }, () => sentence(40)).join("\n\n") + "\n");
    const r = ste([many, "--nonce", "n-42"]);
    expect(r.code).toBe(1);
    expect(r.stdout.trim().split("\n")).toHaveLength(1);
    expect(r.stdout.length).toBeLessThanOrEqual(1024);
    expect(r.out).toMatchObject({ ok: true, cmd: "stelint", nonce: "n-42", verdict: "fail", evidence: r.evidence });
    expect(r.out.sha256).toBe(createHash("sha256").update(readFileSync(r.evidence)).digest("hex"));
    expect(r.findings).toHaveLength(80);

    const pass = doc([fixture("valid/design-log.md")]);
    expect(pass.out).toMatchObject({ ok: true, cmd: "doclint", nonce: null, verdict: "pass" });

    // Errors still print one JSON object and exit 2: a missing path, a bad option, a bad lock record.
    const missing = ste([join(scratch, "nope.md"), "--nonce", "n-43"]);
    expect([missing.code, missing.out.verdict, missing.out.ok, missing.out.nonce]).toEqual([2, "error", false, "n-43"]);
    const bad = Bun.spawnSync([PY, STELINT, "--mode", "bogus", "--nonce", "n-44"], { cwd: scratch });
    expect(bad.exitCode).toBe(2);
    expect(JSON.parse(bad.stdout.toString())).toMatchObject({ verdict: "error", nonce: "n-44" });
    const badLock = write("bad.lock", "not json\n");
    const lockErr = doc([fixture("valid/design-log.md"), "--lock-file", badLock]);
    expect([lockErr.code, lockErr.out.verdict]).toEqual([2, "error"]);
  });
});
