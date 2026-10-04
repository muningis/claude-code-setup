#!/bin/bash
# A stand-in for `claude -p` in the dream tests. $1 is -p and $2 is the prompt.
# It logs its flags, counts its calls, and writes the candidates file that the prompt names.
: "${FAKE_CLAUDE_LOG:?}"
out=$(printf '%s\n' "$2" | sed -n 's/^- candidates\.json: \(.*\) (write your output here)$/\1/p')
printf '%s\n' "$2" >"$FAKE_CLAUDE_LOG.prompt"
shift 2
printf '%s\n' "$@" >"$FAKE_CLAUDE_LOG"
echo call >>"$FAKE_CLAUDE_LOG.calls"
cp "$FAKE_CANDIDATES" "$out"
