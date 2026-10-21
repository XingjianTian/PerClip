#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${PERCLIP_BASE_URL:-http://127.0.0.1:18081}"
TOKEN="${PERCLIP_INGEST_TOKEN:-dev-token}"
REQUEST_ID="${PERCLIP_SMOKE_REQUEST_ID:-smoke-$(date +%Y%m%d%H%M%S)}"

require_json_boolean_ok() {
  local label="$1"
  local body="$2"
  RESPONSE_LABEL="$label" RESPONSE_BODY="$body" python3 - <<'PY'
import json
import os
import sys

label = os.environ["RESPONSE_LABEL"]
body = os.environ["RESPONSE_BODY"]
try:
    payload = json.loads(body)
except json.JSONDecodeError as exc:
    print(f"{label} did not return valid JSON: {exc}", file=sys.stderr)
    sys.exit(1)

if payload.get("ok") is not True:
    print(f"{label} must return JSON boolean ok: true.", file=sys.stderr)
    sys.exit(1)
PY
}

echo "Checking ${BASE_URL}/health"
health_body="$(curl -fsS "${BASE_URL}/health")"
printf '%s\n' "$health_body"
require_json_boolean_ok "GET /health" "$health_body"
echo

echo "Checking authenticated mobile token"
verify_body="$(curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  "${BASE_URL}/api/mobile-clips/verify")"
printf '%s\n' "$verify_body"
require_json_boolean_ok "GET /api/mobile-clips/verify" "$verify_body"
echo

echo "Posting text clip ${REQUEST_ID}"
upload_body="$(curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "source_type=text" \
  -F "title_hint=PerClip smoke test" \
  -F "text=PerClip smoke test from scripts/smoke_server.sh" \
  -F "note=server smoke" \
  -F "device_name=mac-smoke" \
  -F "source_app=script" \
  -F "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -F "client_request_id=${REQUEST_ID}" \
  "${BASE_URL}/api/mobile-clips")"
printf '%s\n' "$upload_body"
require_json_boolean_ok "POST /api/mobile-clips" "$upload_body"
echo
