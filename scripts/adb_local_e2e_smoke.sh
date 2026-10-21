#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/_android_tools.sh"

PACKAGE="${PERCLIP_APP_PACKAGE:-com.sudox.perclip.dev}"
TOKEN="${PERCLIP_INGEST_TOKEN:-dev-token}"
PORT="${PERCLIP_E2E_PORT:-18081}"
APP_API_URL="${PERCLIP_APP_API_URL:-http://10.0.2.2:${PORT}}"
DEVICE_NAME="${PERCLIP_APP_DEVICE_NAME:-Android E2E PerClip}"
SHARE_TEXT="${1:-https://example.com PerClip local e2e smoke}"
UI_DUMP_PATH="/sdcard/perclip-local-e2e-smoke.xml"

ADB="$(require_adb)"
DEVICE_OUTPUT="$(select_device_arg "$ADB")"
DEVICE_ARG=()
while IFS= read -r arg; do
  DEVICE_ARG+=("$arg")
done <<< "$DEVICE_OUTPUT"

COMPONENT="$(resolve_main_component "$PACKAGE" "$ADB" "${DEVICE_ARG[@]}")"

server_pid=""
server_log=""
data_dir=""

cleanup() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" >/dev/null 2>&1; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  [[ -n "$server_log" && -f "$server_log" ]] && rm -f "$server_log"
  [[ -n "$data_dir" && -d "$data_dir" ]] && rm -rf "$data_dir"
}
trap cleanup EXIT

step() {
  printf '\n==> %s\n' "$1"
}

adb_shell_quote() {
  local value="$1"
  printf "'%s'" "$(printf '%s' "$value" | sed "s/'/'\\\\''/g")"
}

ensure_server_venv() {
  if [[ ! -d "$ROOT_DIR/.venv" ]]; then
    python3 -m venv "$ROOT_DIR/.venv"
  fi
  "$ROOT_DIR/.venv/bin/python" -m pip install -q -e "$ROOT_DIR/server[dev]"
}

wait_for_server() {
  local base_url="$1"
  for _ in $(seq 1 80); do
    if curl -fsS "$base_url/health" >/dev/null 2>&1; then
      return 0
    fi
    if [[ -n "$server_pid" ]] && ! kill -0 "$server_pid" >/dev/null 2>&1; then
      echo "Local server exited before becoming ready." >&2
      [[ -f "$server_log" ]] && cat "$server_log" >&2
      return 1
    fi
    sleep 0.25
  done
  echo "Local server did not become ready at $base_url." >&2
  [[ -f "$server_log" ]] && cat "$server_log" >&2
  return 1
}

start_local_server() {
  step "Start local PerClip ingest API"
  ensure_server_venv
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "Port ${PORT} already has a responding service. Stop it or set PERCLIP_E2E_PORT." >&2
    return 1
  fi
  server_log="$(mktemp -t perclip-adb-e2e-server.XXXXXX.log)"
  data_dir="$(mktemp -d -t perclip-adb-e2e-data.XXXXXX)"
  (
    cd "$ROOT_DIR/server"
    PERCLIP_INGEST_TOKEN="$TOKEN" \
      PERCLIP_DATA_DIR="$data_dir" \
      PERCLIP_ENABLE_CLIP_TO_RAGFLOW=0 \
      "$ROOT_DIR/.venv/bin/python" -m uvicorn perclip_ingest.main:create_app \
        --factory \
        --host 0.0.0.0 \
        --port "$PORT"
  ) >"$server_log" 2>&1 &
  server_pid="$!"
  wait_for_server "http://127.0.0.1:${PORT}"
  echo "Local ingest API is ready at http://127.0.0.1:${PORT}"
  echo "App API URL: ${APP_API_URL}"
}

install_debug_apk() {
  if [[ "${PERCLIP_E2E_SKIP_INSTALL:-false}" == "true" ]]; then
    step "Skip APK install"
    return 0
  fi
  step "Install debug APK"
  "$ROOT_DIR/scripts/install_debug_apk.sh"
}

configure_app() {
  step "Configure debug app settings"
  PERCLIP_APP_API_URL="$APP_API_URL" \
    PERCLIP_APP_INGEST_TOKEN="$TOKEN" \
    PERCLIP_APP_DEVICE_NAME="$DEVICE_NAME" \
    PERCLIP_APP_WIFI_ONLY_LARGE_FILES=false \
    PERCLIP_APP_PERSISTENT_QUICK_ENTRY=false \
    "$ROOT_DIR/scripts/configure_debug_app_settings.sh"
}

wake_device() {
  "$ADB" "${DEVICE_ARG[@]}" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1 || true
  "$ADB" "${DEVICE_ARG[@]}" shell wm dismiss-keyguard >/dev/null 2>&1 || true
}

wait_for_foreground() {
  for _ in $(seq 1 30); do
    local focus
    focus="$("$ADB" "${DEVICE_ARG[@]}" shell dumpsys activity activities 2>/dev/null | grep -E 'mResumedActivity|topResumedActivity' || true)"
    if [[ "$focus" == *"$PACKAGE"* ]]; then
      return 0
    fi
    sleep 0.25
  done
  "$ADB" "${DEVICE_ARG[@]}" shell dumpsys activity activities 2>/dev/null | grep -E 'mResumedActivity|topResumedActivity' || true
  echo "PerClip did not become the foreground activity." >&2
  return 1
}

dump_ui() {
  "$ADB" "${DEVICE_ARG[@]}" shell uiautomator dump "$UI_DUMP_PATH" >/dev/null
  "$ADB" "${DEVICE_ARG[@]}" exec-out cat "$UI_DUMP_PATH" 2>/dev/null | tr -d '\r'
}

ui_contains_any() {
  local dump="$1"
  shift
  local expected
  for expected in "$@"; do
    if grep -F -- "$expected" <<< "$dump" >/dev/null; then
      return 0
    fi
  done
  return 1
}

wait_for_ui_contains_any() {
  local label="$1"
  shift
  local dump
  for _ in $(seq 1 60); do
    dump="$(dump_ui)"
    if ui_contains_any "$dump" "$@"; then
      echo "PASS ${label}"
      return 0
    fi
    sleep 0.5
  done
  echo "Timed out waiting for ${label}." >&2
  echo "Expected one of:" >&2
  local expected
  for expected in "$@"; do
    echo "  - $expected" >&2
  done
  dump_ui >&2
  return 1
}

tap_ui_text() {
  local label="$1"
  shift
  local dump
  dump="$(dump_ui)"
  local point
  if ! point="$(UI_DUMP="$dump" python3 - "$@" <<'PY'
import re
import os
import sys
import xml.etree.ElementTree as ET

needles = sys.argv[1:]
xml = os.environ["UI_DUMP"]
root = ET.fromstring(xml)

for node in root.iter("node"):
    haystack = " ".join(
        node.attrib.get(name, "")
        for name in ("text", "content-desc", "resource-id")
    )
    if any(needle in haystack for needle in needles):
        bounds = node.attrib.get("bounds", "")
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not match:
            continue
        left, top, right, bottom = map(int, match.groups())
        print((left + right) // 2, (top + bottom) // 2)
        sys.exit(0)

sys.exit(1)
PY
)"; then
    echo "Could not find tappable UI text for ${label}." >&2
    dump_ui >&2
    return 1
  fi
  read -r x y <<< "$point"
  echo "Tap ${label} at ${x},${y}"
  "$ADB" "${DEVICE_ARG[@]}" shell input tap "$x" "$y"
}

launch_share() {
  step "Launch ACTION_SEND share"
  local subject_arg
  local text_arg
  local component_arg
  subject_arg="$(adb_shell_quote "PerClip local E2E")"
  text_arg="$(adb_shell_quote "$SHARE_TEXT")"
  component_arg="$(adb_shell_quote "$COMPONENT")"
  "$ADB" "${DEVICE_ARG[@]}" shell am force-stop "$PACKAGE"
  "$ADB" "${DEVICE_ARG[@]}" shell "am start -W -a android.intent.action.SEND -t text/plain --es android.intent.extra.SUBJECT $subject_arg --es android.intent.extra.TEXT $text_arg -n $component_arg" >/dev/null
  wait_for_foreground
  wait_for_ui_contains_any "share review screen" "保存到 PersonalClips" "补充备注"
}

save_share_and_wait_for_upload() {
  step "Save share and wait for upload"
  tap_ui_text "保存到 PersonalClips" "保存到 PersonalClips"
  wait_for_ui_contains_any "uploaded recents row" "刚刚已入库" "已入库" "已提交 NAS 入库服务。"
}

verify_server_received_clip() {
  step "Verify local server stored clip"
  local db_path="$data_dir/perclip.sqlite3"
  if [[ ! -f "$db_path" ]]; then
    echo "Expected SQLite metadata at ${db_path}" >&2
    return 1
  fi
  "$ROOT_DIR/.venv/bin/python" - "$db_path" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
conn = sqlite3.connect(db_path)
rows = conn.execute(
    "select title_hint, device_name, archive_status, original_path from clips order by id desc limit 1"
).fetchall()
if not rows:
    print("No uploaded clip rows found.", file=sys.stderr)
    sys.exit(1)
title, device_name, archive_status, original_path = rows[0]
if archive_status != "local":
    print(f"Expected local archive status, got {archive_status!r}.", file=sys.stderr)
    sys.exit(1)
if not original_path:
    print("Expected original_path to be populated.", file=sys.stderr)
    sys.exit(1)
print(f"Stored clip: {title} | {device_name} | {archive_status} | {original_path}")
PY
}

wake_device
install_debug_apk
start_local_server
configure_app
launch_share
save_share_and_wait_for_upload
verify_server_received_clip

echo
echo "PerClip adb local E2E smoke passed."
