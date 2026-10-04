if [ "$1" = "--shout" ]; then
  echo "Hello, ${2:-world}" | tr 'a-z' 'A-Z'
else
  echo "Hello, ${1:-world}"
fi
