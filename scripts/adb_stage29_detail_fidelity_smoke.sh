#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/_android_tools.sh"

PACKAGE="${PERCLIP_APP_PACKAGE:-com.sudox.perclip.dev}"
COMPONENT="${PACKAGE}/com.sudox.perclip.debug.KnowledgeEvidenceActivity"
UI_DUMP_PATH="/sdcard/perclip-stage29-detail.xml"
EXPECTED="来源忠实原文：Example Domain。此内容来自已安全存储的当前屏幕闪记。"
FORBIDDEN="不应优先显示的处理文本"

ADB="$(require_adb)"
DEVICE_OUTPUT="$(select_device_arg "$ADB")"
DEVICE_ARG=()
while IFS= read -r arg; do DEVICE_ARG+=("$arg"); done <<< "$DEVICE_OUTPUT"

if [[ "${PERCLIP_STAGE29_SKIP_INSTALL:-false}" != "true" ]]; then
  "$ROOT_DIR/scripts/install_debug_apk.sh"
fi

dump_ui() {
  "$ADB" "${DEVICE_ARG[@]}" shell uiautomator dump "$UI_DUMP_PATH" >/dev/null
  "$ADB" "${DEVICE_ARG[@]}" exec-out cat "$UI_DUMP_PATH" 2>/dev/null | tr -d '\r'
}

verify_detail() {
  local dump=""
  for _ in $(seq 1 50); do
    dump="$(dump_ui)"
    if grep -F -- "$EXPECTED" <<< "$dump" >/dev/null; then
      if grep -F -- "$FORBIDDEN" <<< "$dump" >/dev/null; then
        echo "Processed text incorrectly outranked original text." >&2
        exit 1
      fi
      grep -F -- "Stage 29 ScreenClip" <<< "$dump" >/dev/null
      grep -F -- "Chrome · com.android.chrome" <<< "$dump" >/dev/null
      echo "PASS: Stage 29 source-faithful detail is visible"
      return 0
    fi
    sleep 0.4
  done
  echo "Timed out waiting for Stage 29 detail." >&2
  dump_ui >&2
  exit 1
}

start_fixture() {
  "$ADB" "${DEVICE_ARG[@]}" shell am force-stop "$PACKAGE"
  "$ADB" "${DEVICE_ARG[@]}" shell am start -W -n "$COMPONENT" --es fixture detail-stage29-original >/dev/null
  verify_detail
}

start_fixture
start_fixture
echo "Stage 29 detail fidelity and App restart smoke passed."
