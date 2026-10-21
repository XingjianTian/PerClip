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
UI_DUMP_PATH="/sdcard/perclip-notification-entry-smoke.xml"

COMPONENT="$(resolve_main_component "$PACKAGE" "$ADB" "${DEVICE_ARG[@]}")"

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
  local attempts=30
  for _ in $(seq 1 "$attempts"); do
    local focus
    focus="$("$ADB" "${DEVICE_ARG[@]}" shell dumpsys activity activities 2>/dev/null | grep -E 'mResumedActivity|topResumedActivity' || true)"
    if [[ "$focus" == *"$PACKAGE"* ]]; then
      return 0
    fi
    sleep 0.25
  done
  "$ADB" "${DEVICE_ARG[@]}" shell dumpsys activity activities 2>/dev/null | grep -E 'mResumedActivity|topResumedActivity' || true
  fail "PerClip did not become the foreground activity."
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

tap_ui_text() {
  local label="$1"
  shift
  local dump
  dump="$(dump_ui)"
  local point
  if ! point="$(UI_DUMP="$dump" python3 - "$@" <<'PY'
import os
import re
import sys
import xml.etree.ElementTree as ET

needles = sys.argv[1:]
root = ET.fromstring(os.environ["UI_DUMP"])

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

grant_notification_permission() {
  "$ADB" "${DEVICE_ARG[@]}" shell pm grant "$PACKAGE" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || true
}

configure_quick_entry() {
  PERCLIP_APP_API_URL="${PERCLIP_APP_API_URL:-http://10.0.2.2:18081}" \
    PERCLIP_APP_INGEST_TOKEN="${PERCLIP_APP_INGEST_TOKEN:-dev-token}" \
    PERCLIP_APP_DEVICE_NAME="${PERCLIP_APP_DEVICE_NAME:-Android Notification PerClip}" \
    PERCLIP_APP_WIFI_ONLY_LARGE_FILES="${PERCLIP_APP_WIFI_ONLY_LARGE_FILES:-false}" \
    PERCLIP_APP_PERSISTENT_QUICK_ENTRY=true \
    "$ROOT_DIR/scripts/configure_debug_app_settings.sh"
}

launch_app_to_sync_notification() {
  "$ADB" "${DEVICE_ARG[@]}" shell am start -W -n "$COMPONENT" >/dev/null
  wait_for_foreground
}

wait_for_notification() {
  for _ in $(seq 1 40); do
    local notification_dump
    notification_dump="$("$ADB" "${DEVICE_ARG[@]}" shell dumpsys notification --noredact 2>/dev/null || true)"
    if [[ "$notification_dump" == *"$PACKAGE"* && "$notification_dump" == *"PerClip 闪记"* ]]; then
      echo "PASS notification posted"
      return 0
    fi
    sleep 0.5
  done
  "$ADB" "${DEVICE_ARG[@]}" shell dumpsys notification --noredact 2>/dev/null | grep -A8 -B4 "$PACKAGE" || true
  fail "PerClip quick-entry notification was not posted."
}

tap_notification() {
  "$ADB" "${DEVICE_ARG[@]}" shell cmd statusbar expand-notifications >/dev/null 2>&1 || \
    "$ADB" "${DEVICE_ARG[@]}" shell service call statusbar 1 >/dev/null 2>&1 || true
  wait_for_ui_contains_any "notification shade" "PerClip 闪记" "点一下，记录到 PersonalClips"
  tap_ui_text "PerClip quick-entry notification" "PerClip 闪记" "点一下，记录到 PersonalClips"
  wait_for_foreground
  wait_for_ui_contains_any "quick-entry destination" "新建闪记" "保存闪记"
}

wake_device
grant_notification_permission
configure_quick_entry
launch_app_to_sync_notification
wait_for_notification
tap_notification

echo
echo "PerClip quick-entry notification smoke passed."
