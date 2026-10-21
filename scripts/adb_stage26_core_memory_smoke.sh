#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/_android_tools.sh"

PACKAGE="${PERCLIP_APP_PACKAGE:-com.sudox.perclip.dev}"
COMPONENT="${PACKAGE}/com.sudox.perclip.debug.KnowledgeEvidenceActivity"
UI_DUMP_PATH="/sdcard/perclip-stage26-core-memory.xml"
SEARCH_TERM="zhihu-010"
EXPECTED_TITLE="Core Memory zhihu-010"

ADB="$(require_adb)"
DEVICE_OUTPUT="$(select_device_arg "$ADB")"
DEVICE_ARG=()
while IFS= read -r arg; do DEVICE_ARG+=("$arg"); done <<< "$DEVICE_OUTPUT"

dump_ui() {
  "$ADB" "${DEVICE_ARG[@]}" shell uiautomator dump "$UI_DUMP_PATH" >/dev/null
  "$ADB" "${DEVICE_ARG[@]}" exec-out cat "$UI_DUMP_PATH" 2>/dev/null | tr -d '\r'
}

wait_for_text() {
  local expected="$1"
  local dump
  for _ in $(seq 1 50); do
    dump="$(dump_ui)"
    if grep -F -- "$expected" <<< "$dump" >/dev/null; then
      echo "PASS: found '$expected'"
      return 0
    fi
    sleep 0.4
  done
  echo "Timed out waiting for '$expected'." >&2
  dump_ui >&2
  exit 1
}

ui_point_for_text() {
  local dump="$1"
  local needle="$2"
  UI_DUMP="$dump" python3 - "$needle" <<'PY'
import os
import re
import sys
import xml.etree.ElementTree as ET

root = ET.fromstring(os.environ["UI_DUMP"])
needle = sys.argv[1]
for node in root.iter("node"):
    haystack = " ".join(node.attrib.get(name, "") for name in ("text", "content-desc", "resource-id"))
    if needle not in haystack:
        continue
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.attrib.get("bounds", ""))
    if match:
        left, top, right, bottom = map(int, match.groups())
        print((left + right) // 2, (top + bottom) // 2)
        raise SystemExit(0)
raise SystemExit(1)
PY
}

tap_text() {
  local needle="$1"
  local point x y
  point="$(ui_point_for_text "$(dump_ui)" "$needle")"
  read -r x y <<< "$point"
  "$ADB" "${DEVICE_ARG[@]}" shell input tap "$x" "$y"
}

if [[ "${PERCLIP_STAGE26_SKIP_INSTALL:-false}" != "true" ]]; then
  "$ROOT_DIR/scripts/install_debug_apk.sh"
fi

"$ADB" "${DEVICE_ARG[@]}" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1 || true
"$ADB" "${DEVICE_ARG[@]}" shell wm dismiss-keyguard >/dev/null 2>&1 || true
"$ADB" "${DEVICE_ARG[@]}" shell am force-stop "$PACKAGE"
"$ADB" "${DEVICE_ARG[@]}" shell am start -W -n "$COMPONENT" --es fixture stage26 >/dev/null

wait_for_text "本机 60 条"
tap_text "搜索标题、摘要、平台或文件名"
"$ADB" "${DEVICE_ARG[@]}" shell input text "$SEARCH_TERM"
wait_for_text "本机 1 条"
wait_for_text "$EXPECTED_TITLE"
tap_text "$EXPECTED_TITLE"
wait_for_text "$EXPECTED_TITLE"
wait_for_text "分享一些常用工具和工作流，希望对你有帮助。"
"$ADB" "${DEVICE_ARG[@]}" shell input keyevent KEYCODE_BACK
wait_for_text "本机 1 条"
wait_for_text "$EXPECTED_TITLE"
tap_text "$SEARCH_TERM"
"$ADB" "${DEVICE_ARG[@]}" shell input keyevent KEYCODE_MOVE_END
for _ in $(seq 1 ${#SEARCH_TERM}); do
  "$ADB" "${DEVICE_ARG[@]}" shell input keyevent KEYCODE_DEL
done
wait_for_text "本机 60 条"

echo "Stage 26 Core Memory Android smoke passed."
