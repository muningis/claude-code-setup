"""Remove secrets from text and cap its length, before the text goes into a dream file."""
from __future__ import annotations

import re

CAP = 600
# A hostile line could slow the patterns down, so cut the input first.
PRE_CAP = 4000
# Session text may carry a long paste. Callers that read sessions scrub up to this many characters
# before they cut the result.
SESSION_PRE_CAP = 20000
MASK = "[redacted]"

_KEY_WORDS = (r"password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key"
              r"|private[_-]?key|credentials?")

# Order matters: the multi-line block and the URL form go first, the generic key=value form last.
_RULES = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S),
     "[redacted private key]"),
    # A lookbehind, not \b: a match may only start at the beginning of a run, or a long dotted run takes O(n^2).
    (re.compile(r"(?i)(?<![a-z0-9+.\-])([a-z][a-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@"), r"\1" + MASK + "@"),
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*)(?:(?:bearer|basic|token)\s+)?[^\s\"']+"), r"\1" + MASK),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 " + MASK),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), MASK),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), MASK),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), MASK),
    (re.compile(r"\bxox[abprso]-[A-Za-z0-9-]{10,}"), MASK),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), MASK),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), MASK),
    (re.compile(r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{16,}"), MASK),
    (re.compile(r"\bnpm_[A-Za-z0-9]{36}"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), MASK),
    (re.compile(r"(?i)(--(?:password|passwd|token|secret|api-key|access-key)(?:=|\s+))\S+"), r"\1" + MASK),
    # The key must END in a secret word, so `TokenStore: x` stays but `GITHUB_TOKEN=x` goes.
    (re.compile(r"(?i)((?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]*(?:" + _KEY_WORDS + r")[\"']?\s*=\s*)"
                r"(\"[^\"]*\"|'[^']*'|[^\s,;&\"'}\])]+)"), r"\1" + MASK),
    # After a colon, prose is common ("token: the oracle uses it"). Redact a quoted value, a value with
    # a digit, and a long one: a secret is rarely a short word.
    (re.compile(r"(?i)((?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]*(?:" + _KEY_WORDS + r")[\"']?\s*:\s*)"
                r"(\"[^\"]*\"|'[^']*'|(?=[^\s,;&\"'}\])]*\d)[^\s,;&\"'}\])]+|[^\s,;&\"'}\])]{12,})"),
     r"\1" + MASK),
    # An address names a person. `git@host` is the user of a git remote, so it stays.
    (re.compile(r"(?<![A-Za-z0-9._%+-])(?!git@)[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"),
     "[email]"),
]


def scrub(text, pre_cap=PRE_CAP):
    """The text with every secret that a pattern finds replaced by a mask."""
    out = str(text)[:pre_cap]
    for rx, repl in _RULES:
        out = rx.sub(repl, out)
    return out


def clean(text, cap=CAP, pre_cap=PRE_CAP):
    """Scrub first, then cut: a secret that straddles the cap must not survive as a prefix."""
    out = " ".join(scrub(text, pre_cap).split())
    if len(out) > cap:
        out = out[:cap - 3].rstrip() + "..."
    return out
