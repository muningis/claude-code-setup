# FR-003 shouts the greeting when asked
out=$(sh src/greet.sh --shout Ada)
if [ "$out" != "HELLO, ADA" ]; then
  echo "AssertionError: expected 'HELLO, ADA' but got '$out'"
  exit 1
fi
