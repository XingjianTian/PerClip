#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${PERCLIP_ENV_LOADED:-}" != "1" ]]; then
  exec "$ROOT_DIR/scripts/with_env.sh" env PERCLIP_ENV_LOADED=1 bash "$0" "$@"
fi
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/_android_tools.sh"

failures=0
warnings=0

pass() {
  printf 'PASS  %s\n' "$1"
}

warn() {
  warnings=$((warnings + 1))
  printf 'WARN  %s\n' "$1"
}

fail() {
  failures=$((failures + 1))
  printf 'FAIL  %s\n' "$1"
}

is_placeholder() {
  local value="${1:-}"
  [[ -z "$value" || "$value" == change-me-* ]]
}

echo "PerClip E2E readiness"
echo

if [[ -x "$ROOT_DIR/android/gradlew" ]]; then
  pass "Gradle wrapper is executable"
else
  fail "android/gradlew is missing or not executable"
fi

apk_path="$ROOT_DIR/android/app/build/outputs/apk/debug/app-debug.apk"
if [[ -f "$apk_path" ]]; then
  pass "Debug APK exists at android/app/build/outputs/apk/debug/app-debug.apk"
  if "$ROOT_DIR/scripts/audit_android_apk.sh" "$apk_path"; then
    pass "Debug APK audit passed"
  else
    fail "Debug APK audit failed"
  fi
else
  fail "Debug APK is missing; run (cd android && ./gradlew assembleDebug)"
fi

if adb_path="$(find_adb)"; then
  pass "adb found at $adb_path"
  device_count="$("$adb_path" devices | awk 'NR > 1 && $2 == "device" { count += 1 } END { print count + 0 }')"
  if [[ -n "${ANDROID_SERIAL:-}" ]]; then
    if "$adb_path" -s "$ANDROID_SERIAL" get-state >/dev/null 2>&1; then
      pass "ANDROID_SERIAL device is authorized: $ANDROID_SERIAL"
    else
      fail "ANDROID_SERIAL is set but not authorized/reachable: $ANDROID_SERIAL"
    fi
  elif (( device_count > 0 )); then
    pass "Authorized Android device count: $device_count"
  else
    fail "No authorized Android device is connected"
  fi
else
  fail "adb not found; install Android SDK platform-tools or add adb to PATH"
fi

echo
echo "Server env"

env_file="${PERCLIP_ENV_FILE:-$ROOT_DIR/.env}"
if [[ -f "$env_file" ]]; then
  pass "private .env loaded explicitly"
else
  fail "private .env is missing; copy the root .env.example and fill server-side values"
fi

if is_placeholder "${PERCLIP_INGEST_TOKEN:-}"; then
  fail "PERCLIP_INGEST_TOKEN is missing or still a placeholder"
else
  pass "PERCLIP_INGEST_TOKEN is set"
fi

if [[ "${PERCLIP_INGEST_TOKEN:-}" =~ [[:space:]] ]]; then
  fail "PERCLIP_INGEST_TOKEN contains whitespace"
fi

plugin_dir="${PERCLIP_CLIP_TO_RAGFLOW_DIR:-/path/to/KnowledgeBase/plugins/ClipToRAGFlow}"
if [[ -d "$plugin_dir/clip_to_ragflow" ]]; then
  pass "ClipToRAGFlow plugin package exists"
else
  fail "ClipToRAGFlow plugin package not found under $plugin_dir"
fi

if [[ -n "${PERSONAL_CLIPS_ROOT:-}" && -d "${PERSONAL_CLIPS_ROOT:-}" ]]; then
  pass "PERSONAL_CLIPS_ROOT exists"
else
  fail "PERSONAL_CLIPS_ROOT is missing or not mounted"
fi

dataset_id="${PERSONAL_CLIPS_DATASET_ID:-${RAGFLOW_DATASET_ID:-}}"
if is_placeholder "$dataset_id"; then
  fail "PERSONAL_CLIPS_DATASET_ID/RAGFLOW_DATASET_ID is missing or still a placeholder"
else
  pass "PersonalClips dataset id is set"
fi

if is_placeholder "${RAGFLOW_API_KEY:-}"; then
  fail "RAGFLOW_API_KEY is missing or still a placeholder"
else
  pass "RAGFLOW_API_KEY is set"
fi

if [[ -n "${RAGFLOW_BASE_URL:-}" ]]; then
  pass "RAGFLOW_BASE_URL is set to ${RAGFLOW_BASE_URL}"
else
  warn "RAGFLOW_BASE_URL is not set; ClipToRAGFlow will rely on its own defaults"
fi

echo
if (( failures > 0 )); then
  echo "Readiness failed: ${failures} failure(s), ${warnings} warning(s)."
  exit 1
fi

echo "Readiness passed: ${warnings} warning(s)."
