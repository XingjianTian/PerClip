#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/_android_tools.sh"

ADB="$(require_adb)"
DEVICE_OUTPUT="$(select_device_arg "$ADB")"
DEVICE_ARG=()
while IFS= read -r arg; do
  DEVICE_ARG+=("$arg")
done <<< "$DEVICE_OUTPUT"

PACKAGE="${PERCLIP_APP_PACKAGE:-com.sudox.perclip.dev}"
UI_DUMP_PATH="/sdcard/perclip-qs-tile-smoke.xml"

MAIN_COMPONENT="$(resolve_main_component "$PACKAGE" "$ADB" "${DEVICE_ARG[@]}")"
TILE_COMPONENT="${PACKAGE}/com.sudox.perclip.quicksettings.QuickCaptureTileService"

fail() {
  echo "$1" >&2
  exit 1
}

if ! "$ADB" "${DEVICE_ARG[@]}" shell pm path "$PACKAGE" >/dev/null 2>&1; then
  fail "PerClip is not installed on the selected device. Run scripts/install_debug_apk.sh first."
fi

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
  fail "PerClip did not become the foreground activity after clicking the QS tile."
}

dump_ui() {
  "$ADB" "${DEVICE_ARG[@]}" shell uiautomator dump "$UI_DUMP_PATH" >/dev/null
  "$ADB" "${DEVICE_ARG[@]}" exec-out cat "$UI_DUMP_PATH" 2>/dev/null | tr -d '\r'
}

wait_for_ui_contains_any() {
  local label="$1"
  shift
  local dump
  for _ in $(seq 1 40); do
    dump="$(dump_ui)"
    local expected
    for expected in "$@"; do
      if grep -F -- "$expected" <<< "$dump" >/dev/null; then
        echo "PASS ${label}: found '${expected}'"
        return 0
      fi
    done
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

check_qs_support() {
  local output
  output="$("$ADB" "${DEVICE_ARG[@]}" shell cmd statusbar check-support 2>&1 || true)"
  if [[ "$output" == *"false"* || "$output" == *"not supported"* || "$output" == *"Unknown command"* ]]; then
    echo "$output" >&2
    fail "This device does not expose supported cmd statusbar QS tile APIs."
  fi
}

add_and_click_tile() {
  "$ADB" "${DEVICE_ARG[@]}" shell am force-stop "$PACKAGE" >/dev/null
  "$ADB" "${DEVICE_ARG[@]}" shell cmd statusbar remove-tile "$TILE_COMPONENT" >/dev/null 2>&1 || true
  "$ADB" "${DEVICE_ARG[@]}" shell cmd statusbar add-tile "$TILE_COMPONENT" >/dev/null
  sleep 0.5
  "$ADB" "${DEVICE_ARG[@]}" shell cmd statusbar click-tile "$TILE_COMPONENT" >/dev/null
}

wake_device
check_qs_support
add_and_click_tile
wait_for_foreground
wait_for_ui_contains_any "QS tile destination" "新建闪记" "保存闪记"

"$ADB" "${DEVICE_ARG[@]}" shell cmd statusbar collapse >/dev/null 2>&1 || true

echo
echo "PerClip Quick Settings tile smoke passed."
