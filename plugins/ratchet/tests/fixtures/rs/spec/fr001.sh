# FR-001 greets the user by name
out=$(sh src/greet.sh Ada)
if [ "$out" != "Hello, Ada" ]; then
  echo "AssertionError: expected 'Hello, Ada' but got '$out'"
  exit 1
fi
