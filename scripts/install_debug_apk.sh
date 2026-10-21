#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/_android_tools.sh"

APK_PATH="${1:-$ROOT_DIR/android/app/build/outputs/apk/debug/app-debug.apk}"

if [[ ! -f "$APK_PATH" ]]; then
  echo "Debug APK not found, building it first."
  (cd "$ROOT_DIR/android" && ./gradlew assembleDebug)
fi

echo "Auditing ${APK_PATH}"
"$ROOT_DIR/scripts/audit_android_apk.sh" "$APK_PATH"

ADB="$(require_adb)"
DEVICE_OUTPUT="$(select_device_arg "$ADB")"
DEVICE_ARG=()
while IFS= read -r arg; do
  DEVICE_ARG+=("$arg")
done <<< "$DEVICE_OUTPUT"

echo "Installing ${APK_PATH}"
"$ADB" "${DEVICE_ARG[@]}" install -r "$APK_PATH"
