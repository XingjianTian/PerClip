#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${PERCLIP_BASE_URL:-http://127.0.0.1:18081}"
TOKEN="${PERCLIP_INGEST_TOKEN:-dev-token}"
DATA_DIR="${PERCLIP_DATA_DIR:-}"
REQUEST_ID="${PERCLIP_SMOKE_REQUEST_ID:-enrichment-smoke-$(date +%Y%m%d%H%M%S)}"

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

echo "Posting enrichment smoke clip ${REQUEST_ID}"
upload_body="$(curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "source_type=text" \
  -F "title_hint=PerClip enrichment smoke" \
  -F "text=PerClip deterministic enrichment smoke body" \
  -F "device_name=mac-smoke" \
  -F "source_app=script" \
  -F "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -F "client_request_id=${REQUEST_ID}" \
  "${BASE_URL}/api/mobile-clips")"
printf '%s\n' "$upload_body"
echo

echo "Calling clip enrichment for ${REQUEST_ID}"
enrich_body="$(curl -fsS \
  -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  "${BASE_URL}/api/clips/${REQUEST_ID}/enrich")"
printf '%s\n' "$enrich_body"
enrich_status="$(json_get "$enrich_body" "enrichment.status")"
if [[ "$enrich_status" != "completed" ]]; then
  echo "unexpected enrichment status: ${enrich_status}" >&2
  exit 1
fi
echo

echo "Checking SQLite enrichment and metadata in ${DB_PATH}"
DB_PATH="$DB_PATH" REQUEST_ID="$REQUEST_ID" python3 - <<'PY'
import json
import os
import sqlite3
import sys

db_path = os.environ["DB_PATH"]
request_id = os.environ["REQUEST_ID"]

if not os.path.exists(db_path):
    print(f"SQLite DB not found: {db_path}", file=sys.stderr)
    sys.exit(1)

with sqlite3.connect(db_path) as db:
    enrichment = db.execute(
        """
        select status, engine
        from clip_enrichments
        where client_request_id = ?
        order by id desc
        limit 1
        """,
        (request_id,),
    ).fetchone()
    metadata_row = db.execute(
        """
        select metadata_json
        from clip_metadata
        where client_request_id = ?
        """,
        (request_id,),
    ).fetchone()

if enrichment is None:
    print("clip enrichment not found", file=sys.stderr)
    sys.exit(1)
if enrichment != ("completed", "deterministic.v1"):
    print(f"unexpected enrichment row: {enrichment}", file=sys.stderr)
    sys.exit(1)
if metadata_row is None:
    print("clip metadata not found", file=sys.stderr)
    sys.exit(1)

metadata = json.loads(metadata_row[0])
if metadata.get("enrichment", {}).get("status") != "completed":
    print("metadata.enrichment.status is not completed", file=sys.stderr)
    sys.exit(1)
for required in ["clip", "provenance", "assets", "processing", "security", "routing"]:
    if required not in metadata:
        print(f"metadata missing required section: {required}", file=sys.stderr)
        sys.exit(1)

print("enrichment smoke passed")
PY
