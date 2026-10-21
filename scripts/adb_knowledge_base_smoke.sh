#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/_android_tools.sh"

PACKAGE="${PERCLIP_APP_PACKAGE:-com.sudox.perclip.dev}"
UI_DUMP_PATH="/sdcard/perclip-kb-smoke.xml"

ADB="$(require_adb)"
DEVICE_OUTPUT="$(select_device_arg "$ADB")"
DEVICE_ARG=()
while IFS= read -r arg; do
  DEVICE_ARG+=("$arg")
done <<< "$DEVICE_OUTPUT"

COMPONENT="$(resolve_main_component "$PACKAGE" "$ADB" "${DEVICE_ARG[@]}")"

step() {
  printf '\n==> %s\n' "$1"
}

fail() {
  echo "$1" >&2
  exit 1
}

dump_ui() {
  "$ADB" "${DEVICE_ARG[@]}" shell uiautomator dump "$UI_DUMP_PATH" >/dev/null
  "$ADB" "${DEVICE_ARG[@]}" exec-out cat "$UI_DUMP_PATH" 2>/dev/null | tr -d '\r'
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
  fail "PerClip did not become the foreground activity."
}

wait_for_ui_text() {
  local label="$1"
  shift
  local dump expected
  for _ in $(seq 1 50); do
    dump="$(dump_ui)"
    for expected in "$@"; do
      if grep -F -- "$expected" <<< "$dump" >/dev/null; then
        echo "PASS ${label}: found '${expected}'"
        return 0
      fi
    done
    sleep 0.4
  done
  echo "Timed out waiting for ${label}. Expected one of:" >&2
  for expected in "$@"; do
    echo "  - $expected" >&2
  done
  dump_ui >&2
  exit 1
}

ui_point_for_text() {
  local dump="$1"
  shift
  UI_DUMP="$dump" python3 - "$@" <<'PY'
import os
import re
import sys
import xml.etree.ElementTree as ET

needles = sys.argv[1:]
root = ET.fromstring(os.environ["UI_DUMP"])
for node in root.iter("node"):
    haystack = " ".join(node.attrib.get(name, "") for name in ("text", "content-desc", "resource-id"))
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
}

tap_ui_text() {
  local label="$1"
  shift
  local dump point x y
  dump="$(dump_ui)"
  if ! point="$(ui_point_for_text "$dump" "$@")"; then
    echo "Could not find tappable UI text for ${label}." >&2
    echo "$dump" >&2
    return 1
  fi
  read -r x y <<< "$point"
  echo "Tap ${label} at ${x},${y}"
  "$ADB" "${DEVICE_ARG[@]}" shell input tap "$x" "$y"
}

install_debug_apk() {
  if [[ "${PERCLIP_KB_SMOKE_SKIP_INSTALL:-false}" == "true" ]]; then
    step "Skip APK install"
    return 0
  fi
  step "Install debug APK"
  "$ROOT_DIR/scripts/install_debug_apk.sh"
}

wake_device() {
  "$ADB" "${DEVICE_ARG[@]}" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1 || true
  "$ADB" "${DEVICE_ARG[@]}" shell wm dismiss-keyguard >/dev/null 2>&1 || true
}

reset_app_data() {
  if [[ "${PERCLIP_KB_SMOKE_SKIP_CLEAR:-false}" == "true" || "${PERCLIP_KB_SMOKE_SKIP_RESET:-false}" == "true" ]]; then
    step "Skip app data reset"
    return 0
  fi
  step "Reset debug app data"
  "$ADB" "${DEVICE_ARG[@]}" shell pm clear "$PACKAGE" >/dev/null
}

open_settings_and_kb_management() {
  step "Open Knowledge Base management"
  "$ADB" "${DEVICE_ARG[@]}" shell am start -W -a com.sudox.perclip.action.SETTINGS -n "$COMPONENT" >/dev/null
  wait_for_foreground
  wait_for_ui_text "settings entry" "知识库管理" "打开知识库管理"
  tap_ui_text "knowledge base management" "知识库管理"
  if [[ "${PERCLIP_KB_SMOKE_EXPECT_SERVER:-false}" == "true" ]]; then
    wait_for_ui_text "knowledge base default list" "个人收藏"
  else
    wait_for_ui_text "knowledge base management screen" "Android 只调用 PerClip 服务端" "请先填写 NAS API 地址和 mobile ingest token"
  fi
}

open_save_screen_and_verify_target() {
  step "Open save screen and verify target hint"
  "$ADB" "${DEVICE_ARG[@]}" shell am start -W -n "$COMPONENT" >/dev/null
  wait_for_foreground
  if [[ "${PERCLIP_KB_SMOKE_EXPECT_SERVER:-false}" == "true" ]]; then
    wait_for_ui_text "save target" "将保存到：个人收藏" "fallback default"
  else
    wait_for_ui_text "save target" "将保存到：默认知识库" "将保存到："
  fi
}

main() {
  install_debug_apk
  wake_device
  reset_app_data
  open_settings_and_kb_management
  open_save_screen_and_verify_target
  echo "Knowledge Base Android smoke passed."
}

main "$@"
