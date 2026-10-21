#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/generate_mobile_token.sh [--env]

Generate a strong PerClip mobile ingest token.

Options:
  --env    Print as PERCLIP_INGEST_TOKEN=<token> for pasting into the root .env.

The token is printed once and is not saved by this script.
EOF
}

FORMAT="raw"
if [[ "${1:-}" == "--env" ]]; then
  FORMAT="env"
elif [[ $# -gt 0 ]]; then
  usage >&2
  exit 2
fi

TOKEN_BYTES="${PERCLIP_TOKEN_BYTES:-32}"
case "$TOKEN_BYTES" in
  ''|*[!0-9]*)
    echo "PERCLIP_TOKEN_BYTES must be a positive integer." >&2
    exit 2
    ;;
esac

if (( TOKEN_BYTES < 32 )); then
  echo "PERCLIP_TOKEN_BYTES must be at least 32 bytes." >&2
  exit 2
fi

token="$(
  python3 - "$TOKEN_BYTES" <<'PY'
import secrets
import sys

byte_count = int(sys.argv[1])
print(secrets.token_urlsafe(byte_count))
PY
)"

if [[ "$token" =~ [[:space:]] || -z "$token" ]]; then
  echo "Generated token was invalid." >&2
  exit 1
fi

if [[ "$FORMAT" == "env" ]]; then
  printf 'PERCLIP_INGEST_TOKEN=%s\n' "$token"
else
  printf '%s\n' "$token"
fi
