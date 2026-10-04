# FR-002 greets the world when no name is given
out=$(sh src/greet.sh)
if [ "$out" != "Hello, world" ]; then
  echo "AssertionError: expected 'Hello, world' but got '$out'"
  exit 1
fi
