#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/_android_tools.sh"

PACKAGE="${PERCLIP_APP_PACKAGE:-com.sudox.perclip.dev}"
UI_DUMP_PATH="/sdcard/perclip-clip-library-smoke.xml"
SMOKE_KEYWORD="${PERCLIP_LIBRARY_SMOKE_KEYWORD:-cliplibsmoke}"
SHARE_SUBJECT="${PERCLIP_LIBRARY_SMOKE_SUBJECT:-PerClip library smoke}"
SHARE_TEXT="${1:-${SMOKE_KEYWORD} local library validation note}"

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

adb_shell_quote() {
  local value="$1"
  printf "'%s'" "$(printf '%s' "$value" | sed "s/'/'\\\\''/g")"
}

install_debug_apk() {
  if [[ "${PERCLIP_LIBRARY_SMOKE_SKIP_INSTALL:-false}" == "true" ]]; then
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
  if [[ "${PERCLIP_LIBRARY_SMOKE_SKIP_CLEAR:-false}" == "true" ]]; then
    step "Skip app data reset"
    return 0
  fi
  step "Reset debug app data"
  "$ADB" "${DEVICE_ARG[@]}" shell pm clear "$PACKAGE" >/dev/null
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
  fail "PerClip did not become the foreground activity."
}

dump_ui() {
  "$ADB" "${DEVICE_ARG[@]}" shell uiautomator dump "$UI_DUMP_PATH" >/dev/null
  "$ADB" "${DEVICE_ARG[@]}" exec-out cat "$UI_DUMP_PATH" 2>/dev/null | tr -d '\r'
}

assert_ui_contains_any() {
  local label="$1"
  shift
  local dump
  dump="$(dump_ui)"
  local expected
  for expected in "$@"; do
    if grep -F -- "$expected" <<< "$dump" >/dev/null; then
      echo "PASS ${label}: found '${expected}'"
      return 0
    fi
  done

  echo "UI dump for ${label} did not contain expected text." >&2
  echo "Expected one of:" >&2
  for expected in "$@"; do
    echo "  - $expected" >&2
  done
  echo "$dump" >&2
  exit 1
}

ui_contains_any() {
  local dump="$1"
  shift
  local expected
  for expected in "$@"; do
    if grep -F -- "$expected" <<< "$dump" >/dev/null; then
      echo "$expected"
      return 0
    fi
  done
  return 1
}

wait_for_ui_contains_any() {
  local label="$1"
  shift
  local dump found
  for _ in $(seq 1 50); do
    dump="$(dump_ui)"
    if found="$(ui_contains_any "$dump" "$@")"; then
      echo "PASS ${label}: found '${found}'"
      return 0
    fi
    sleep 0.4
  done
  echo "Timed out waiting for ${label}." >&2
  echo "Expected one of:" >&2
  local expected
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

ui_point_for_exact_text() {
  local dump="$1"
  shift
  UI_DUMP="$dump" python3 - "$@" <<'PY'
import os
import re
import sys
import xml.etree.ElementTree as ET

needles = set(sys.argv[1:])
root = ET.fromstring(os.environ["UI_DUMP"])
for node in root.iter("node"):
    text = node.attrib.get("text", "")
    content_desc = node.attrib.get("content-desc", "")
    if text not in needles and content_desc not in needles:
        continue
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

ui_point_for_first_edit_text() {
  local dump="$1"
  UI_DUMP="$dump" python3 - <<'PY'
import os
import re
import sys
import xml.etree.ElementTree as ET

root = ET.fromstring(os.environ["UI_DUMP"])
for node in root.iter("node"):
    if node.attrib.get("class") != "android.widget.EditText":
        continue
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

tap_ui_exact_text() {
  local label="$1"
  shift
  local dump point x y
  dump="$(dump_ui)"
  if ! point="$(ui_point_for_exact_text "$dump" "$@")"; then
    echo "Could not find tappable exact UI text for ${label}." >&2
    echo "$dump" >&2
    return 1
  fi
  read -r x y <<< "$point"
  echo "Tap ${label} at ${x},${y}"
  "$ADB" "${DEVICE_ARG[@]}" shell input tap "$x" "$y"
}

tap_search_field() {
  local dump point x y
  dump="$(dump_ui)"
  if ! point="$(ui_point_for_text "$dump" "搜索闪记")"; then
    point="$(ui_point_for_first_edit_text "$dump")" || {
      echo "Could not find tappable UI text for library search field." >&2
      echo "$dump" >&2
      return 1
    }
  fi
  read -r x y <<< "$point"
  echo "Tap library search field at ${x},${y}"
  "$ADB" "${DEVICE_ARG[@]}" shell input tap "$x" "$y"
}

replace_search_text() {
  local value="$1"
  tap_search_field
  # Clear the previous query by deleting more characters than any smoke input uses.
  for _ in $(seq 1 40); do
    "$ADB" "${DEVICE_ARG[@]}" shell input keyevent KEYCODE_DEL >/dev/null
  done
  if [[ -n "$value" ]]; then
    "$ADB" "${DEVICE_ARG[@]}" shell input text "$value" >/dev/null
  fi
  sleep 0.5
}

launch_share_and_save() {
  step "Create one local queue record through ACTION_SEND"
  local subject_arg text_arg component_arg
  subject_arg="$(adb_shell_quote "$SHARE_SUBJECT")"
  text_arg="$(adb_shell_quote "$SHARE_TEXT")"
  component_arg="$(adb_shell_quote "$COMPONENT")"
  "$ADB" "${DEVICE_ARG[@]}" shell am force-stop "$PACKAGE"
  "$ADB" "${DEVICE_ARG[@]}" shell "am start -W -a android.intent.action.SEND -t text/plain --es android.intent.extra.SUBJECT $subject_arg --es android.intent.extra.TEXT $text_arg -n $component_arg" >/dev/null
  wait_for_foreground
  wait_for_ui_contains_any "share review screen" "一键闪记" "保存到 PersonalClips" "补充备注"
  tap_ui_exact_text "share save action" "一键闪记" "保存到 PersonalClips"
  wait_for_ui_contains_any "clip library after save" "闪记库" "$SMOKE_KEYWORD" "入库概览"
}

open_clip_library() {
  step "Open Clip Library"
  "$ADB" "${DEVICE_ARG[@]}" shell am start -W -a com.sudox.perclip.action.RECENTS -n "$COMPONENT" >/dev/null
  wait_for_foreground
  wait_for_ui_contains_any "clip library screen" "闪记库" "搜索闪记"
}

verify_library_chrome() {
  step "Verify search and filter controls"
  assert_ui_contains_any "search field" "搜索闪记"
  assert_ui_contains_any "status overview filters" "全部" "待处理" "已入库" "失败"
  assert_ui_contains_any "compact type filter" "全部类型"
}

verify_filter_interactions() {
  step "Verify status and type filter interactions"
  tap_ui_text "waiting status filter" "待处理"
  wait_for_ui_contains_any "record after status filter" "$SMOKE_KEYWORD" "$SHARE_SUBJECT"
  tap_ui_text "type filter button" "全部类型"
  wait_for_ui_contains_any "type filter sheet" "类型筛选" "text"
  tap_ui_exact_text "text type filter" "text"
  wait_for_ui_contains_any "record after type filter" "$SMOKE_KEYWORD" "$SHARE_SUBJECT"
}

verify_detail_round_trip() {
  step "Verify detail view and return"
  tap_ui_exact_text "record detail action" "详情"
  wait_for_ui_contains_any "detail title" "$SMOKE_KEYWORD" "$SHARE_SUBJECT"
  assert_ui_contains_any "detail basic section" "基本信息"
  assert_ui_contains_any "detail upload status" "上传状态"
  tap_ui_text "detail back" "返回"
  wait_for_ui_contains_any "library list after back" "搜索闪记" "$SMOKE_KEYWORD"
}

verify_search() {
  step "Verify search hit and empty-result states"
  replace_search_text "$SMOKE_KEYWORD"
  wait_for_ui_contains_any "search hit" "$SMOKE_KEYWORD" "$SHARE_SUBJECT"
  replace_search_text "nomatchcliplibrary"
  wait_for_ui_contains_any "search empty state" "没有匹配的闪记" "换个关键词或减少筛选条件后再试。"
}

wake_device
install_debug_apk
reset_app_data
launch_share_and_save
open_clip_library
verify_library_chrome
verify_filter_interactions
verify_detail_round_trip
verify_search

echo
echo "PerClip Clip Library adb smoke passed."
