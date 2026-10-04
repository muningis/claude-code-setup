#!/bin/sh
# Test runner of the fixture project: runs each script it is given and fails when one fails.
rc=0
for t in "$@"; do
  sh "$t" || rc=1
done
exit "$rc"
