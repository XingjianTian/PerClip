#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${PERCLIP_BASE_URL:-http://127.0.0.1:18081}"
TOKEN="${PERCLIP_INGEST_TOKEN:-dev-token}"
DATA_DIR="${PERCLIP_DATA_DIR:-}"
REQUEST_ID="${PERCLIP_SMOKE_REQUEST_ID:-move-smoke-$(date +%Y%m%d%H%M%S)}"
SOURCE_KB_NAME="${PERCLIP_SMOKE_SOURCE_KB_NAME:-Move Source $(date +%H%M%S)}"
TARGET_KB_NAME="${PERCLIP_SMOKE_TARGET_KB_NAME:-Move Target $(date +%H%M%S)}"

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

create_kb() {
  local name="$1"
  curl -fsS \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"${name}\",\"description\":\"server clip move smoke\"}" \
    "${BASE_URL}/api/knowledge-bases"
}

echo "Creating source Knowledge Base: ${SOURCE_KB_NAME}"
source_body="$(create_kb "$SOURCE_KB_NAME")"
printf '%s\n' "$source_body"
source_kb_id="$(json_get "$source_body" "knowledge_base.id")"
echo

echo "Creating target Knowledge Base: ${TARGET_KB_NAME}"
target_body="$(create_kb "$TARGET_KB_NAME")"
printf '%s\n' "$target_body"
target_kb_id="$(json_get "$target_body" "knowledge_base.id")"
echo

echo "Posting mobile clip ${REQUEST_ID} to ${source_kb_id}"
upload_body="$(curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "source_type=text" \
  -F "title_hint=PerClip move smoke" \
  -F "text=PerClip clip move smoke" \
  -F "device_name=mac-smoke" \
  -F "source_app=script" \
  -F "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -F "client_request_id=${REQUEST_ID}" \
  -F "target_knowledge_base_id=${source_kb_id}" \
  "${BASE_URL}/api/mobile-clips")"
printf '%s\n' "$upload_body"
echo

clip_id="$(DB_PATH="$DB_PATH" REQUEST_ID="$REQUEST_ID" python3 - <<'PY'
import os
import sqlite3

with sqlite3.connect(os.environ["DB_PATH"]) as db:
    row = db.execute(
        "select id from clips where client_request_id = ?",
        (os.environ["REQUEST_ID"],),
    ).fetchone()
if row is None:
    raise SystemExit("clip row not found")
print(row[0])
PY
)"

echo "Moving clip ${clip_id} to ${target_kb_id}"
move_body="$(curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"target_knowledge_base_id\":\"${target_kb_id}\",\"reason\":\"user moved from Clip Library detail\"}" \
  "${BASE_URL}/api/clips/${clip_id}/move")"
printf '%s\n' "$move_body"
echo

echo "Checking SQLite move decision in ${DB_PATH}"
DB_PATH="$DB_PATH" REQUEST_ID="$REQUEST_ID" SOURCE_KB_ID="$source_kb_id" TARGET_KB_ID="$target_kb_id" python3 - <<'PY'
import json
import os
import sqlite3
import sys

db_path = os.environ["DB_PATH"]
request_id = os.environ["REQUEST_ID"]
source_kb_id = os.environ["SOURCE_KB_ID"]
target_kb_id = os.environ["TARGET_KB_ID"]

if not os.path.exists(db_path):
    print(f"SQLite DB not found: {db_path}", file=sys.stderr)
    sys.exit(1)

with sqlite3.connect(db_path) as db:
    rows = db.execute(
        """
        select knowledge_base_id, previous_knowledge_base_id, decision_type,
               manual_override, reindex_status
        from clip_route_decisions
        where client_request_id = ?
        order by id asc
        """,
        (request_id,),
    ).fetchall()
    metadata_row = db.execute(
        "select metadata_json from clip_metadata where client_request_id = ?",
        (request_id,),
    ).fetchone()

if len(rows) != 2:
    print(f"expected 2 route decisions, found {len(rows)}", file=sys.stderr)
    sys.exit(1)

first, latest = rows
if first[0] != source_kb_id:
    print(f"unexpected source route decision: {first}", file=sys.stderr)
    sys.exit(1)
if latest[0] != target_kb_id or latest[1] != source_kb_id or latest[2] != "manual":
    print(f"unexpected latest route decision: {latest}", file=sys.stderr)
    sys.exit(1)
if int(latest[3]) != 1 or latest[4] != "required":
    print(f"move decision missing manual override/reindex requirement: {latest}", file=sys.stderr)
    sys.exit(1)
if metadata_row is None:
    print("metadata row not found", file=sys.stderr)
    sys.exit(1)

routing = json.loads(metadata_row[0]).get("routing", {})
if routing.get("knowledge_base_id") != target_kb_id or routing.get("reindex_status") != "required":
    print(f"unexpected metadata routing: {routing}", file=sys.stderr)
    sys.exit(1)

print("clip move smoke passed")
PY
