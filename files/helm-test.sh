#!/bin/sh
# `helm test`: checks that a release answers. Reads one check per line from $CHECKS:
#   <name> http <url>         needs a status of exactly 200; redirects are not followed
#   <name> tcp <host>:<port>  only needs to connect
# Runs in the OpenCloud image, which has curl and nc.
TIMEOUT=10

http() {
  code=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time "$TIMEOUT" "$1")
  if [ "$code" = 200 ]; then
    echo "HTTP 200"
  elif [ "$code" = 000 ] || [ -z "$code" ]; then
    echo "no HTTP answer from $1"
    return 1
  else
    echo "expected HTTP 200, got $code"
    return 1
  fi
}

tcp() {
  if nc -z -w "$TIMEOUT" "${1%:*}" "${1##*:}"; then
    echo "connected"
  else
    echo "cannot connect to $1"
    return 1
  fi
}

main() {
  failed=0
  while read -r name type target; do
    [ -n "$name" ] || continue
    case "$type" in
      http | tcp)
        if result=$("$type" "$target"); then
          echo "ok    $name: $result"
        else
          echo "FAIL  $name: $result"
          failed=$((failed + 1))
        fi
        ;;
      *)
        echo "FAIL  $name: unknown check type '$type'"
        failed=$((failed + 1))
        ;;
    esac
  done
  if [ "$failed" -gt 0 ]; then
    echo "$failed check(s) failed"
    return 1
  fi
  echo "all checks passed"
}

main <<EOF
$CHECKS
EOF
