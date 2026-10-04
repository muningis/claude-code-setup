#!/bin/bash
# A stand-in for `claude -p` in the dream tests. $1 is -p and $2 is the prompt.
# It logs its flags and its folder, counts its calls, and writes candidates.json in the folder it runs in.
: "${FAKE_CLAUDE_LOG:?}"
printf '%s\n' "$2" >"$FAKE_CLAUDE_LOG.prompt"
shift 2
printf '%s\n' "$@" >"$FAKE_CLAUDE_LOG"
pwd -P >"$FAKE_CLAUDE_LOG.pwd"
echo call >>"$FAKE_CLAUDE_LOG.calls"
cp "$FAKE_CANDIDATES" candidates.json
