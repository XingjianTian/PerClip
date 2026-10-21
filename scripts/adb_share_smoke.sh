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
TEXT="${1:-https://example.com PerClip Android share smoke}"

COMPONENT="$(resolve_main_component "$PACKAGE" "$ADB" "${DEVICE_ARG[@]}")"

adb_shell_quote() {
  local value="$1"
  printf "'%s'" "$(printf '%s' "$value" | sed "s/'/'\\\\''/g")"
}

if ! "$ADB" "${DEVICE_ARG[@]}" shell pm path "$PACKAGE" >/dev/null 2>&1; then
  echo "PerClip is not installed on the selected device. Run scripts/install_debug_apk.sh first." >&2
  exit 2
fi

echo "Launching PerClip with ACTION_SEND text."
SUBJECT_ARG="$(adb_shell_quote "PerClip smoke")"
TEXT_ARG="$(adb_shell_quote "$TEXT")"
COMPONENT_ARG="$(adb_shell_quote "$COMPONENT")"
"$ADB" "${DEVICE_ARG[@]}" shell "am start -a android.intent.action.SEND -t text/plain --es android.intent.extra.SUBJECT $SUBJECT_ARG --es android.intent.extra.TEXT $TEXT_ARG -n $COMPONENT_ARG"

echo "The app should show the share review screen. Tap 保存 in the app to enqueue upload."
