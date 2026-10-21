#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${PERCLIP_ENV_LOADED:-}" != "1" ]]; then
  exec "$ROOT_DIR/scripts/with_env.sh" env PERCLIP_ENV_LOADED=1 bash "$0" "$@"
fi

export PERCLIP_INGEST_TOKEN="${PERCLIP_INGEST_TOKEN:-}"
export PERCLIP_DATA_DIR="${PERCLIP_DATA_DIR:-$ROOT_DIR/server/data}"
export PERCLIP_HOST="${PERCLIP_HOST:-0.0.0.0}"
export PERCLIP_PORT="${PERCLIP_PORT:-18081}"
export PERCLIP_ENABLE_CLIP_TO_RAGFLOW=1
export PERCLIP_CLIP_TO_RAGFLOW_DIR="${PERCLIP_CLIP_TO_RAGFLOW_DIR:-/path/to/KnowledgeBase/plugins/ClipToRAGFlow}"
export PERSONAL_CLIPS_ROOT="${PERSONAL_CLIPS_ROOT:-}"
export RAGFLOW_BASE_URL="${RAGFLOW_BASE_URL:-}"

missing=()
placeholders=()
invalid=()

is_placeholder() {
  local value="${1:-}"
  [[ "$value" == change-me-* ]]
}

require_real_value() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" ]]; then
    missing+=("$name")
    return
  fi
  if is_placeholder "$value"; then
    placeholders+=("$name")
  fi
}

require_real_value "PERCLIP_INGEST_TOKEN"
[[ -d "$PERCLIP_CLIP_TO_RAGFLOW_DIR/clip_to_ragflow" ]] || missing+=("PERCLIP_CLIP_TO_RAGFLOW_DIR/clip_to_ragflow")
require_real_value "PERSONAL_CLIPS_ROOT"
if [[ -n "${PERSONAL_CLIPS_ROOT:-}" && ! -d "$PERSONAL_CLIPS_ROOT" ]]; then
  missing+=("PERSONAL_CLIPS_ROOT directory")
fi

DATASET_ID="${PERSONAL_CLIPS_DATASET_ID:-${RAGFLOW_DATASET_ID:-}}"
if [[ -z "$DATASET_ID" ]]; then
  missing+=("PERSONAL_CLIPS_DATASET_ID or RAGFLOW_DATASET_ID")
elif is_placeholder "$DATASET_ID"; then
  placeholders+=("PERSONAL_CLIPS_DATASET_ID or RAGFLOW_DATASET_ID")
fi

require_real_value "RAGFLOW_API_KEY"

if [[ "$PERCLIP_INGEST_TOKEN" =~ [[:space:]] ]]; then
  invalid+=("PERCLIP_INGEST_TOKEN must not contain whitespace")
fi

if (( ${#missing[@]} > 0 || ${#placeholders[@]} > 0 || ${#invalid[@]} > 0 )); then
  echo "Missing required server-side settings:" >&2
  if (( ${#missing[@]} > 0 )); then
    printf '  - %s\n' "${missing[@]}" >&2
  fi
  if (( ${#placeholders[@]} > 0 )); then
    echo "Settings still using server/.env.example placeholders:" >&2
    printf '  - %s\n' "${placeholders[@]}" >&2
  fi
  if (( ${#invalid[@]} > 0 )); then
    echo "Invalid server-side settings:" >&2
    printf '  - %s\n' "${invalid[@]}" >&2
  fi
  echo "Copy server/.env.example to server/.env and fill the real NAS/RAGFlow values." >&2
  exit 2
fi

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -q -e "server[dev]"

echo "PerClip ingest API: ClipToRAGFlow mode"
echo "  health:  http://127.0.0.1:${PERCLIP_PORT}/health"
echo "  plugin:  ${PERCLIP_CLIP_TO_RAGFLOW_DIR}"
echo "  archive: ${PERSONAL_CLIPS_ROOT}"

exec uvicorn perclip_ingest.main:create_app \
  --factory \
  --host "$PERCLIP_HOST" \
  --port "$PERCLIP_PORT"
