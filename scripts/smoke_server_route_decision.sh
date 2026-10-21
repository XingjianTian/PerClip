#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${PERCLIP_BASE_URL:-http://127.0.0.1:18081}"
TOKEN="${PERCLIP_INGEST_TOKEN:-dev-token}"
DATA_DIR="${PERCLIP_DATA_DIR:-}"
REQUEST_ID="${PERCLIP_SMOKE_REQUEST_ID:-route-smoke-$(date +%Y%m%d%H%M%S)}"
KB_NAME="${PERCLIP_SMOKE_KB_NAME:-Route Smoke $(date +%H%M%S)}"

if [[ -z "$DATA_DIR" ]]; then
  echo "PERCLIP_DATA_DIR is required so the smoke can inspect perclip.sqlite3." >&2
  exit 2
fi

DB_PATH="${DATA_DIR%/}/perclip.sqlite3"

json_get() {
  local body="$1"
  local path="$2"
  JSON_BODY="$body" JSON_PATH="$path" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["JSON_BODY"])
value = payload
for part in os.environ["JSON_PATH"].split("."):
    value = value[part]
print(value)
PY
}

echo "Creating Knowledge Base: ${KB_NAME}"
kb_body="$(curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${KB_NAME}\",\"description\":\"server route decision smoke\"}" \
  "${BASE_URL}/api/knowledge-bases")"
printf '%s\n' "$kb_body"
kb_id="$(json_get "$kb_body" "knowledge_base.id")"
echo

echo "Posting mobile clip ${REQUEST_ID} to ${kb_id}"
upload_body="$(curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "source_type=text" \
  -F "title_hint=PerClip route smoke" \
  -F "text=PerClip route decision smoke" \
  -F "device_name=mac-smoke" \
  -F "source_app=script" \
  -F "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -F "client_request_id=${REQUEST_ID}" \
  -F "target_knowledge_base_id=${kb_id}" \
  "${BASE_URL}/api/mobile-clips")"
printf '%s\n' "$upload_body"
echo

echo "Checking SQLite route decision in ${DB_PATH}"
DB_PATH="$DB_PATH" REQUEST_ID="$REQUEST_ID" KB_ID="$kb_id" python3 - <<'PY'
import os
import sqlite3
import sys

db_path = os.environ["DB_PATH"]
request_id = os.environ["REQUEST_ID"]
kb_id = os.environ["KB_ID"]

if not os.path.exists(db_path):
    print(f"SQLite DB not found: {db_path}", file=sys.stderr)
    sys.exit(1)

with sqlite3.connect(db_path) as db:
    row = db.execute(
        """
        select knowledge_base_id, decision_type, manual_override
        from clip_route_decisions
        where client_request_id = ?
        order by id desc
        limit 1
        """,
        (request_id,),
    ).fetchone()

if row is None:
    print("route decision not found", file=sys.stderr)
    sys.exit(1)

knowledge_base_id, decision_type, manual_override = row
if knowledge_base_id != kb_id or decision_type != "manual" or int(manual_override) != 1:
    print(
        f"unexpected route decision: knowledge_base_id={knowledge_base_id}, "
        f"decision_type={decision_type}, manual_override={manual_override}",
        file=sys.stderr,
    )
    sys.exit(1)

print("route decision smoke passed")
PY
