#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/server${PYTHONPATH:+:$PYTHONPATH}"
exec uv run --project "$ROOT_DIR/server" --env-file "${PERCLIP_ENV_FILE:-$ROOT_DIR/.env}" "$@"
