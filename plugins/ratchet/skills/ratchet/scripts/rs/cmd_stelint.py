#!/usr/bin/env python3
"""RS stelint: check the STE-lite writing rules of ratchet's docs.md.

Usage: cmd_stelint.py PATH... [--mode lite|full|off] [--out FILE]
       [--format json|text] [--nonce N]
Exit code: 0 pass, 1 block findings, 2 error.
cmd_doclint.py imports the markdown helpers from this file.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import traceback

CMD = "stelint"
CODE = "\ue000"  # stands for one masked inline code span, and counts as one word
STDOUT_MAX = 1000  # contracts.md caps stdout at 1 KB

SENT_MAX = 25
STEP_MAX = 20
# ASD-STE100 limits each sentence of a procedure step, not the step as a whole. "step" counts all
# words of the step together, which is stricter than the standard.
STEP_SCOPE = "sentence"
PARA_MAX = 6
CLUSTER_MIN = 4


# ---------------------------------------------------------------- output

class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def peek_option(argv, name):
    """Read an option value before argparse runs, so that an error can echo it."""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a[len(name) + 1:]
    return None


def find_git_root(start):
    d = os.path.realpath(start)
    while True:
        if os.path.exists(os.path.join(d, ".git")):  # a file in a worktree
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def repo_rel(path):
    real = os.path.realpath(path)
    root = find_git_root(os.path.dirname(real))
    return os.path.relpath(real, root) if root else path


def finding(path, line, severity, rule, message):
    return {"path": path, "line": line, "severity": severity, "rule": rule, "message": message}


def text_line(f):
    return "%s:%d: %s %s %s" % (f["path"], f["line"], f["severity"], f["rule"], f["message"])


def _print_json(result):
    line = json.dumps(result, ensure_ascii=True)
    summary = result["summary"]
    while len(line) > STDOUT_MAX and summary:
        summary = summary[: max(0, len(summary) - max(8, len(line) - STDOUT_MAX))]
        result = dict(result, summary=summary + "...")
        line = json.dumps(result, ensure_ascii=True)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def emit(cmd, nonce, fmt, out, verdict, summary, findings, extra=None):
    """Print the result, write the evidence file and return the exit code."""
    result = {"ok": verdict != "error", "cmd": cmd, "nonce": nonce,
              "verdict": verdict, "summary": summary}
    result.update(extra or {})
    if fmt == "text":
        data = "".join(text_line(f) + "\n" for f in findings).encode("utf-8", "replace")
    else:
        rel = dict((f["path"], repo_rel(f["path"])) for f in findings)
        evidence = dict(result)
        evidence["findings"] = [dict(f, path=rel[f["path"]]) for f in findings]
        data = (json.dumps(evidence, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if out:
        d = os.path.dirname(os.path.abspath(out))
        os.makedirs(d, exist_ok=True)
        with open(out, "wb") as fh:
            fh.write(data)
        result["evidence"] = out
        result["sha256"] = hashlib.sha256(data).hexdigest()
    if fmt == "text":
        sys.stdout.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        sys.stderr.write(summary + "\n")
    else:
        _print_json(result)
    return {"pass": 0, "fail": 1}.get(verdict, 2)


def fail(cmd, nonce, fmt, message):
    if fmt == "text":
        sys.stderr.write("error: %s\n" % message)
    else:
        _print_json({"ok": False, "cmd": cmd, "nonce": nonce, "verdict": "error",
                     "summary": message})
    return 2


def tally(findings):
    blocking = sum(1 for f in findings if f["severity"] == "block")
    return blocking, len(findings) - blocking


def expand_paths(paths):
    """Return (file, group) pairs. The group is the folder argument, or None."""
    out = []
    seen = set()
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d not in (".git", "node_modules"))
                for name in sorted(names):
                    full = os.path.join(root, name)
                    if name.lower().endswith(".md") and full not in seen:
                        seen.add(full)
                        out.append((full, p))
        elif os.path.isfile(p):
            if p not in seen:
                seen.add(p)
                out.append((p, None))
        else:
            raise UsageError("no such file or folder: %s" % p)
    return out


def read_text(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "replace")


# -------------------------------------------------------- markdown scan

_FM_RE = re.compile(rb"\A(?:\xef\xbb\xbf)?---[ \t]*\r?\n(?:(.*?)\r?\n)?(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.S)


def split_front_matter(data):
    """Return (front matter text or None, byte offset where the body starts)."""
    m = _FM_RE.match(data)
    if not m:
        return None, 0
    return (m.group(1) or b"").decode("utf-8", "replace"), m.end()


def parse_front_matter(text):
    """Read flat `key: value` pairs. This reader does not need nested YAML."""
    out = {}
    for ln in text.split("\n"):
        m = re.match(r"^([A-Za-z][\w-]*)\s*:\s*(.*?)\s*$", ln)
        if m:
            v = m.group(2)
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[m.group(1)] = v
    return out


class Line(object):
    __slots__ = ("no", "kind", "text", "level", "indent", "numbered", "marker")

    def __init__(self, no, kind, text="", level=0, indent=0, numbered=False, marker=False):
        self.no = no
        self.kind = kind  # front code comment heading table blank rule refdef item text
        self.text = text
        self.level = level
        self.indent = indent
        self.numbered = numbered
        self.marker = marker


_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_QUOTE = re.compile(r"^ {0,3}(?:>[ \t]?)+")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_REFDEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*\S")
_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])(?:[ \t]+(.*))?$")
_DELIM = re.compile(r"^\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?$")
_PROC_MARK = re.compile(r"^<!--\s*ste:\s*procedural\s*-->$", re.I)
_TASKBOX = re.compile(r"^\[[ xX]\]\s+")


def split_lines(text):
    return re.split(r"\r\n|\n|\r", text)


def scan(text):
    """Classify each line of a markdown file. Line numbers start at 1."""
    raw = split_lines(text)
    out = []
    fm_end = 0
    if raw and re.match(r"^\ufeff?---[ \t]*$", raw[0]):
        for j in range(1, len(raw)):
            if re.match(r"^(?:---|\.\.\.)[ \t]*$", raw[j]):
                fm_end = j + 1
                break
    for j in range(fm_end):
        out.append(Line(j + 1, "front"))
    fence = None
    in_comment = False
    for j in range(fm_end, len(raw)):
        s = raw[j]
        no = j + 1
        if fence:
            out.append(Line(no, "code"))
            if re.match(r"^\s*%s{%d,}\s*$" % (re.escape(fence[0]), fence[1]), s):
                fence = None
            continue
        if in_comment:
            out.append(Line(no, "comment"))
            if "-->" in s:
                in_comment = False
            continue
        q = _QUOTE.match(s)
        if q:
            s = s[q.end():]
        m = _FENCE.match(s)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = (m.group(1)[0], len(m.group(1)))
            out.append(Line(no, "code"))
            continue
        st = s.strip()
        if st.startswith("<!--"):
            end = st.find("-->")
            if end == -1:
                in_comment = True
                out.append(Line(no, "comment"))
                continue
            if not st[end + 3:].strip():
                out.append(Line(no, "comment", marker=bool(_PROC_MARK.match(st))))
                continue
        if not st:
            out.append(Line(no, "blank"))
            continue
        h = _HEADING.match(s)
        if h:
            title = re.sub(r"[ \t]+#+$", "", (h.group(2) or "").strip())
            out.append(Line(no, "heading", title, level=len(h.group(1))))
            continue
        if _RULE.match(s):
            out.append(Line(no, "rule"))
            continue
        if _REFDEF.match(s):
            out.append(Line(no, "refdef"))
            continue
        if st.startswith("|"):
            out.append(Line(no, "table", st))
            continue
        it = _ITEM.match(s.expandtabs(4))
        if it:
            body = _TASKBOX.sub("", (it.group(3) or "").strip())
            out.append(Line(no, "item", body, indent=len(it.group(1)),
                            numbered=it.group(2)[0].isdigit()))
            continue
        out.append(Line(no, "text", st))
    _mark_tables(out)
    return out


def _mark_tables(lines):
    """Mark tables that have no leading pipe: a header row, a delimiter row, then rows."""
    for k, ln in enumerate(lines):
        if ln.kind != "text" or "|" not in ln.text or not _DELIM.match(ln.text):
            continue
        ln.kind = "table"
        if k > 0 and lines[k - 1].kind == "text" and "|" in lines[k - 1].text:
            lines[k - 1].kind = "table"
        j = k + 1
        while j < len(lines) and lines[j].kind == "text" and "|" in lines[j].text:
            lines[j].kind = "table"
            j += 1


def collect_items(lines, lo, hi):
    """List the items of lines[lo:hi] as (line, indent, numbered, text). Wrapped lines join in."""
    items = []
    cont = False
    for ln in lines[lo:hi]:
        if ln.kind == "item":
            items.append([ln.no, ln.indent, ln.numbered, ln.text])
            cont = True
        elif ln.kind == "text" and cont:
            items[-1][3] = (items[-1][3] + " " + ln.text).strip()
        else:
            cont = False
    return [tuple(i) for i in items]


# ---------------------------------------------------------- inline mask

def _sub(text, lm, rx, fn):
    """Run a regex substitution and keep the per-character line map in step."""
    out = []
    olm = []
    pos = 0
    hit = False
    for m in rx.finditer(text):
        hit = True
        s, e = m.span()
        out.append(text[pos:s])
        olm.extend(lm[pos:s])
        rep = fn(m)
        out.append(rep)
        olm.extend([lm[s]] * len(rep))
        pos = e
    if not hit:
        return text, lm
    out.append(text[pos:])
    olm.extend(lm[pos:])
    return "".join(out), olm


_URL_END = r"[^\s<>.,;:!?'\")\]]"
_LINK_TARGET = r"\((?:[^()\s]|\([^()]*\))*(?:\s+(?:\"[^\"]*\"|'[^']*'))?\)"
_HTML_TAGS = ("a|b|i|u|em|strong|br|p|div|span|img|code|kbd|sub|sup|details|summary|table|thead|tbody|tr|td|th|"
              "ul|ol|li|hr|h[1-6]|pre|small|mark|del|ins|blockquote|center|font")

_INLINE_STEPS = (
    (re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S), lambda m: CODE),
    (re.compile(r"<!--.*?-->", re.S), lambda m: " "),
    (re.compile(r"!\[[^\]]*\]" + _LINK_TARGET), lambda m: " "),
    (re.compile(r"\[([^\]]*)\]" + _LINK_TARGET), lambda m: m.group(1)),
    (re.compile(r"\[([^\]]+)\]\[[^\]]*\]"), lambda m: m.group(1)),
    (re.compile(r"<(?:https?|ftp|mailto):[^>\s]*>"), lambda m: " "),
    (re.compile(r"(?:https?|ftp)://[^\s<>]*" + _URL_END), lambda m: " "),
    (re.compile(r"\bwww\.[^\s<>]*" + _URL_END), lambda m: " "),
    (re.compile(r"\[\^[^\]]+\]"), lambda m: ""),
    (re.compile(r"(\*{1,3})(?=\S)(.+?)(?<=\S)\1", re.S), lambda m: m.group(2)),
    (re.compile(r"(?<![\w])(_{1,3})(?=\S)(.+?)(?<=\S)\1(?![\w])", re.S), lambda m: m.group(2)),
    (re.compile(r"~~(.+?)~~", re.S), lambda m: m.group(1)),
    (re.compile(r"</?(?:%s)\b[^>]*>" % _HTML_TAGS, re.I), lambda m: " "),
    (re.compile(r"<[A-Za-z_][^<>\n]*>"), lambda m: CODE),
    (re.compile(r"\s+"), lambda m: " "),
)


def mask_inline(text, lm):
    for rx, fn in _INLINE_STEPS:
        text, lm = _sub(text, lm, rx, fn)
    lead = len(text) - len(text.lstrip())
    text = text.strip()
    return text, lm[lead:lead + len(text)]


# ---------------------------------------------------- sentences, words

_ABBREV = frozenset("""e.g i.e vs cf viz approx fig figs eq al mr mrs ms dr prof sr jr st inc ltd co ca resp incl
esp""".split())
_END = re.compile(r"([.!?\u2026]+)([\"'\u201d\u2019)\]]*)(?=\s|$)")
_DOTTED = re.compile(r"^(?:[a-z]\.)+[a-z]$")
_STARTERS = "\"'\u201c\u2018(["


def _is_boundary(text, m):
    rest = text[m.end():].lstrip()
    if not rest:
        return True
    c = rest[0]
    if not (c.isupper() or c in _STARTERS or c == CODE):
        return False
    if m.group(1) == ".":
        prev = text[:m.start()].split()
        tok = prev[-1].lstrip("([{\"'\u201c\u2018").lower() if prev else ""
        if tok in _ABBREV or _DOTTED.match(tok):
            return False
    return True


def split_sentences(text):
    """Return (start, end) spans. Abbreviations, decimals and file names do not split."""
    spans = []
    start = 0
    for m in _END.finditer(text):
        if _is_boundary(text, m):
            spans.append((start, m.end()))
            start = m.end()
    spans.append((start, len(text)))
    out = []
    for s, e in spans:
        seg = text[s:e]
        lead = len(seg) - len(seg.lstrip())
        if count_words(seg):
            out.append((s + lead, e))
    return out


def is_word(tok):
    return CODE in tok or any(c.isalnum() for c in tok)


def count_words(text):
    return sum(1 for t in text.split() if is_word(t))


# ----------------------------------------------------------------- units

class Unit(object):
    def __init__(self, kind, no, numbered, proc):
        self.kind = kind  # para or item
        self.no = no
        self.numbered = numbered
        self.proc = proc
        self.segs = []
        self.text = ""
        self.lm = []
        self.sents = []

    def line_at(self, offset):
        if not self.lm:
            return self.no
        return self.lm[min(offset, len(self.lm) - 1)]


_QA = re.compile(r"^(?:Q\d+|A):")
_PROC_HEAD = re.compile(r"(?<![\w])(?:steps?|procedure|how\s+to|install|setup)(?![\w])", re.I)


def build_units(lines):
    """Group lines into paragraphs and list items. Each list item is its own unit."""
    units = []
    cur = None
    head_proc = False
    pending = False
    for ln in lines:
        k = ln.kind
        if k == "text":
            # A Q or A line starts a new unit, as docs.md lays out questions and answers.
            if cur is not None and not _QA.match(ln.text):
                cur.segs.append((ln.no, ln.text))
            else:
                if cur is not None:
                    units.append(cur)
                cur = Unit("para", ln.no, False, pending)
                cur.segs.append((ln.no, ln.text))
                pending = False
            continue
        if cur is not None:
            units.append(cur)
            cur = None
        if k == "item":
            cur = Unit("item", ln.no, ln.numbered, ln.numbered or head_proc)
            if ln.text:
                cur.segs.append((ln.no, ln.text))
            pending = False
        elif k == "heading":
            head_proc = bool(_PROC_HEAD.search(re.sub(r"[`*_]", "", ln.text)))
            pending = False
        elif k == "comment":
            if ln.marker:
                pending = True
        elif k != "blank":
            pending = False
    if cur is not None:
        units.append(cur)
    return units


def prepare(unit):
    """Mask the markup of a unit and split it into sentences."""
    parts = []
    lm = []
    for no, t in unit.segs:
        if parts:
            parts.append(" ")
            lm.append(no)
        parts.append(t)
        lm.extend([no] * len(t))
    text, lm = mask_inline("".join(parts), lm)
    unit.text = text
    unit.lm = lm
    unit.sents = split_sentences(text)
    return unit


def units_of(lines):
    return [prepare(u) for u in build_units(lines)]


# --------------------------------------------------------------- grammar

_FUNC = frozenset("""a an the this that these those my your our their its his her i you he she it we they me him us
them who whom whose which what where when why how and or but nor so yet if then than as because while although though
unless until since once whether either neither both of in on at by for with without within to from into onto over under
between among through during before after above below up down out off about against across along around near per via
is are was were be been being am do does did done have has had can could may might must shall should will would not no
never always also still just only already often now even very too more most less least much many few some any each every
all other another such same own there here again further one two three four five six seven eight nine ten first second
third last next instead however therefore otherwise together apart away back ahead enough rather quite almost soon else
anyway thus hence whenever wherever whatever whichever""".split())

_VERB_BASE = """add allow ask avoid become begin bring build call change check choose close come compare confirm
contain continue copy count cover create cut decide define delete deny describe design detect drop edit end ensure
enter expect explain fail fill find finish fix follow get give go handle hold include keep know label leave let list
load log look lose make mark match mean measure merge move name need note open pass pick pin plan print produce provide
pull push put raise read record reject remove rename repeat replace report require reset restore return reuse review run
save say see send set show skip split start stay stop store take tell test think track try turn type update use verify
wait want watch write apply approve assume attach cause claim clean collect commit compute connect consider convert
declare depend deploy derive differ disable discard display document enable enforce evaluate execute exist extract
fetch filter flag force format generate group guard help hide ignore implement improve increase inspect install launch
limit link lock map mention modify mount observe order output own parse patch point prefer prepare prevent prove
publish queue reach receive reduce refer reflect refuse register relate release rely render request resolve respond
retry reveal revert roll scan schedule score search select serve share sign sort spawn specify spend state stick
submit support surface switch tag target throw trace trigger trust undo unlock upload validate wrap suggest solve
interpret treat propose recommend assign accept access adjust analyze announce answer appear arrange assert associate
attempt authenticate bind block bundle calculate cancel capture clear click combine complete control customize deliver
determine develop download emit encode establish examine exclude expose express extend feed fire fit forward gather
grant identify import indicate inform initialize insert integrate invoke join jump kill learn lift listen locate
maintain manage migrate monitor navigate notify obtain occur offer omit operate optimize override overwrite pair pause
perform place populate post present preserve process prompt protect query quote rebuild recover redirect refresh
remember repair reply represent reserve resume retrieve reverse satisfy simulate sleep step stream strip subscribe
substitute succeed supply suppress swap sync terminate toggle transfer transform translate unpack unwrap upgrade view
visit warn wire work""".split()

_PAST = """ran wrote took made gave went saw came got kept left held built sent found said told thought became began
brought chose drew drove ate fell felt forgot grew heard knew lost met paid rose sold sat spoke spent stood threw woke
won wore""".split()

# Irregular participles. Words that are mostly nouns or adjectives (left, felt, cost) stay out.
_IRREG = frozenset("""begun bitten blown broken brought built bought caught chosen done drawn driven eaten fallen fought
found forgotten forgiven frozen given grown heard held hidden kept known laid led lost made met paid ridden risen run
said seen sent set shaken shown shut sold spoken spent split spread stolen struck sworn taken taught thrown told torn
understood woken won worn written put read cut hit cast""".split())

_SHORT_ED = frozenset(["used", "tied"])
_NOT_ED = frozenset("""hundred kindred sacred naked wicked wretched indeed proceed exceed succeed bleed speed breed
tweed creed greed steed embed""".split())

# Adjectival participles describe a state, so they do not warn as passive.
_ADJ_PART = frozenset("""done finished complete completed based related supposed concerned involved interested excited
tired worried pleased surprised confused married located situated connected dedicated limited detailed advanced
experienced qualified skilled tailored determined committed prepared unused unchanged unknown unsaved unsorted unlisted
enabled disabled hidden broken stuck closed locked pinned blocked skipped sorted required expected allowed supported
deprecated installed configured selected ordered numbered marked aligned centered sized""".split())

_NOT_ING = frozenset("""thing things nothing something anything everything string strings spring springs bring during
morning evening ceiling king ring sing wing swing sting cling fling sling wring""".split())
_ADJ_ING = frozenset("""pending missing outstanding interesting existing remaining following surprising confusing
misleading promising boring exciting amazing challenging daunting annoying willing""".split())

_BE = frozenset("am is are was were be been being isn't aren't wasn't weren't".split())
_HAVE = frozenset(["has", "have", "had"])
_ADV = frozenset("""not never always also still just only already often then now even usually normally first later
finally once ever really simply""".split())


def _verb_forms(v):
    out = {v}
    if v.endswith(("s", "x", "z", "ch", "sh")):
        out.add(v + "es")
    elif len(v) > 1 and v.endswith("y") and v[-2] not in "aeiou":
        out.add(v[:-1] + "ies")
    else:
        out.add(v + "s")
    return out


_STOP = set(_FUNC) | set(_IRREG) | set(_PAST) | _ADJ_PART
for _v in _VERB_BASE:
    _STOP |= _verb_forms(_v)

_PHRASAL = {}
for _forms, _rest in (
        ("carry carries carried carrying", ("out",)),
        ("point points pointed pointing", ("out",)),
        ("find finds found finding", ("out",)),
        ("figure figures figured figuring", ("out",)),
        ("look looks looked looking", ("into",)),
        ("look looks looked looking", ("up",)),
        ("bring brings brought bringing", ("up",)),
        ("give gives gave given giving", ("up",)),
        ("put puts putting", ("off",)),
        ("take takes took taken taking", ("over",)),
        ("end ends ended ending", ("up",)),
        ("turn turns turned turning", ("out",)),
        ("rule rules ruled ruling", ("out",)),
        ("sort sorts sorted sorting", ("out",)),
        ("set sets setting", ("up",)),
        ("come comes came coming", ("up", "with")),
        ("check checks checked checking", ("out",)),
        ("wrap wraps wrapped wrapping", ("up",))):
    for _w in _forms.split():
        _PHRASAL.setdefault(_w, []).append(_rest)


def _tokens(sentence):
    """Return (raw, core, clause_break) for each token. A code span has an empty core."""
    out = []
    for raw in sentence.split():
        if CODE in raw:
            core = ""
        else:
            core = re.sub(r"^[^\w]+|[^\w]+$", "", raw.lower().replace("\u2019", "'"))
        out.append((raw, core, raw[-1:] in ",;:.!?)" or raw in ("-", "\u2013", "\u2014")))
    return out


def _is_adverb(w):
    return w in _ADV or (len(w) > 4 and w.endswith("ly"))


def _after(toks, i):
    """Index of the first token after i that is not an adverb, or None at a clause break."""
    k = i + 1
    skipped = 0
    while k < len(toks):
        if toks[k - 1][2]:
            return None
        if skipped < 2 and _is_adverb(toks[k][1]):
            k += 1
            skipped += 1
            continue
        return k
    return None


def _is_participle(w):
    if w in _IRREG:
        return True
    if w in _SHORT_ED:
        return True
    return len(w) >= 5 and w.endswith("ed") and w not in _NOT_ED and not w.endswith("eed")


def _is_progressive(w):
    if len(w) < 5 or not w.endswith("ing") or w in _NOT_ING or w in _ADJ_ING:
        return False
    return any(c in "aeiouy" for c in w[:-3])  # a stem without a vowel is a noun: thing, ring


def _noun_like(raw, core):
    if CODE in raw or len(core) < 2 or core in _STOP:
        return False
    if not re.match(r"^[a-z][a-z'-]*$", core):
        return False
    return not (core.endswith("ly") or core.endswith("ed") or core.endswith("ing"))


def _clusters(toks):
    out = []
    run = []

    def close():
        if len(run) >= CLUSTER_MIN:
            out.append(list(run))
        del run[:]

    for raw, core, brk in toks:
        if raw[:1] in "([\"'\u201c\u2018":
            close()
        if _noun_like(raw, core):
            run.append(core)
            if brk:
                close()
        else:
            close()
    close()
    return out


def grammar_hits(sentence):
    """Return (rule, phrase) for each style problem in one sentence."""
    toks = _tokens(sentence)
    hits = []
    for i, (raw, w, brk) in enumerate(toks):
        k = _after(toks, i) if (w in _BE or w in _HAVE) else None
        if k is not None:
            nxt = toks[k][1]
            by = k + 1 < len(toks) and toks[k + 1][1] == "by"
            phrase = " ".join(t[1] for t in toks[i:k + 1])
            if w in _BE:
                if _is_progressive(nxt):
                    hits.append(("STE-PROGRESSIVE", phrase))
                elif _is_participle(nxt) and (nxt not in _ADJ_PART or by):
                    hits.append(("STE-PASSIVE", phrase))
            elif nxt == "been" or (_is_participle(nxt) and nxt not in _ADJ_PART):
                hits.append(("STE-PERFECT", phrase))
        for rest in _PHRASAL.get(w, ()):
            end = i + len(rest)
            if end < len(toks) and all(toks[i + 1 + j][1] == rest[j] for j in range(len(rest))) \
                    and not any(toks[i + j][2] for j in range(len(rest))):
                hits.append(("STE-PHRASAL", " ".join([w] + list(rest))))
    for run in _clusters(toks):
        hits.append(("STE-NOUN-CLUSTER", " ".join(run[:6])))
    return hits


# ------------------------------------------------------------------ rules

def lint_units(units, path, full):
    """Apply the length rules and the style rules. Return findings for one file."""
    style = "block" if full else "warn"
    out = []
    for u in units:
        if not u.sents:
            continue
        words = [count_words(u.text[s:e]) for s, e in u.sents]
        if u.proc and STEP_SCOPE == "sentence":
            for (s, e), w in zip(u.sents, words):
                if w > STEP_MAX:
                    out.append(finding(path, u.line_at(s), "block", "STE-STEP-LEN",
                                       "Step sentence has %d words. Keep it to %d or fewer." % (w, STEP_MAX)))
        elif u.proc:
            if sum(words) > STEP_MAX:
                out.append(finding(path, u.no, "block", "STE-STEP-LEN",
                                   "Procedure step has %d words. Keep it to %d or fewer." % (sum(words), STEP_MAX)))
        else:
            for (s, e), w in zip(u.sents, words):
                if w > SENT_MAX:
                    out.append(finding(path, u.line_at(s), "block", "STE-SENT-LEN",
                                       "Sentence has %d words. Keep it to %d or fewer." % (w, SENT_MAX)))
        if len(u.sents) > PARA_MAX:
            what = "Step" if u.proc else "Paragraph"
            out.append(finding(path, u.no, "block", "STE-PARA-LEN",
                               "%s has %d sentences. Keep it to %d or fewer." % (what, len(u.sents), PARA_MAX)))
        for s, e in u.sents:
            for rule, phrase in grammar_hits(u.text[s:e]):
                line = u.line_at(s)
                if rule == "STE-PASSIVE":
                    out.append(finding(path, line, style, rule, "Passive voice: '%s'. Use the active voice." % phrase))
                elif rule == "STE-PERFECT":
                    out.append(finding(path, line, style, rule, "Perfect tense: '%s'. Use a simple tense." % phrase))
                elif rule == "STE-PROGRESSIVE":
                    out.append(finding(path, line, style, rule, "Progressive form: '%s'. Use a simple tense." % phrase))
                elif rule == "STE-PHRASAL":
                    out.append(finding(path, line, style, rule, "Phrasal verb '%s'. Use one verb." % phrase))
                else:
                    out.append(finding(path, line, "warn", rule,
                                       "Noun cluster '%s'. Use 3 words or fewer." % phrase))
    out.sort(key=lambda f: (f["line"], f["rule"]))
    return out


def lint_file(path, full=False):
    return lint_units(units_of(scan(read_text(path))), path, full)


# -------------------------------------------------------------------- cli

def build_parser():
    p = _Parser(prog="cmd_stelint.py", allow_abbrev=False,
                description="Check the STE-lite writing rules in markdown files.")
    p.add_argument("paths", nargs="*", help="markdown files or folders")
    p.add_argument("--mode", choices=("lite", "full", "off"), default="lite")
    p.add_argument("--out", help="write the full findings to this file")
    p.add_argument("--format", choices=("json", "text"), default="json")
    p.add_argument("--nonce", help="echo this value in the result")
    return p


def run(args):
    if args.mode == "off":
        return emit(CMD, args.nonce, args.format, args.out, "pass", "off", [],
                    {"files": 0, "blocking": 0, "warnings": 0})
    if not args.paths:
        raise UsageError("give one or more files or folders")
    files = [f for f, _ in expand_paths(args.paths)]
    findings = []
    for f in files:
        findings.extend(lint_file(f, args.mode == "full"))
    blocking, warns = tally(findings)
    summary = "%d block, %d warn in %d files" % (blocking, warns, len(files))
    return emit(CMD, args.nonce, args.format, args.out, "fail" if blocking else "pass",
                summary, findings, {"files": len(files), "blocking": blocking, "warnings": warns})


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    nonce = peek_option(argv, "--nonce")
    fmt = "text" if peek_option(argv, "--format") == "text" else "json"
    try:
        return run(build_parser().parse_intermixed_args(argv))
    except UsageError as e:
        return fail(CMD, nonce, fmt, str(e))
    except OSError as e:
        return fail(CMD, nonce, fmt, "cannot read or write a file: %s" % e)
    except Exception as e:  # the engine needs a JSON error, never a bare traceback
        traceback.print_exc()
        return fail(CMD, nonce, fmt, "internal error: %s" % e)


if __name__ == "__main__":
    sys.exit(main())
