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
UI_DUMP_PATH="/sdcard/perclip-entrypoint-smoke.xml"
SHARE_TEXT="${1:-https://example.com PerClip Android entrypoint smoke}"

COMPONENT="$(resolve_main_component "$PACKAGE" "$ADB" "${DEVICE_ARG[@]}")"

adb_shell_quote() {
  local value="$1"
  printf "'%s'" "$(printf '%s' "$value" | sed "s/'/'\\\\''/g")"
}

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
  local attempts=20
  local focus
  for _ in $(seq 1 "$attempts"); do
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

launch_main() {
  local label="$1"
  echo
  echo "Launching ${label}"
  "$ADB" "${DEVICE_ARG[@]}" shell am force-stop "$PACKAGE"
  "$ADB" "${DEVICE_ARG[@]}" shell am start -W -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "$COMPONENT" >/dev/null
  wait_for_foreground
}

launch_action() {
  local label="$1"
  local action="$2"
  echo
  echo "Launching ${label}"
  "$ADB" "${DEVICE_ARG[@]}" shell am force-stop "$PACKAGE"
  "$ADB" "${DEVICE_ARG[@]}" shell am start -W -a "$action" -n "$COMPONENT" >/dev/null
  wait_for_foreground
}

launch_share() {
  echo
  echo "Launching share intent"
  local subject_arg
  local text_arg
  local component_arg
  subject_arg="$(adb_shell_quote "PerClip entrypoint smoke")"
  text_arg="$(adb_shell_quote "$SHARE_TEXT")"
  component_arg="$(adb_shell_quote "$COMPONENT")"
  "$ADB" "${DEVICE_ARG[@]}" shell am force-stop "$PACKAGE"
  "$ADB" "${DEVICE_ARG[@]}" shell "am start -W -a android.intent.action.SEND -t text/plain --es android.intent.extra.SUBJECT $subject_arg --es android.intent.extra.TEXT $text_arg -n $component_arg" >/dev/null
  wait_for_foreground
}

wake_device

launch_main "launcher"
assert_ui_contains_any "launcher" "新建闪记" "闪存到 PersonalClips"

launch_action "new note action" "com.sudox.perclip.action.NEW_NOTE"
assert_ui_contains_any "new note action" "新建闪记" "保存闪记"

launch_action "recents action" "com.sudox.perclip.action.RECENTS"
assert_ui_contains_any "recents action" "记忆列表" "知识库"

launch_action "settings action" "com.sudox.perclip.action.SETTINGS"
assert_ui_contains_any "settings action" "设置" "连接设置" "知识库管理"

launch_share
assert_ui_contains_any "share intent" "新建闪记" "保存闪记" "默认保存至"

echo
echo "PerClip entrypoint smoke passed."
