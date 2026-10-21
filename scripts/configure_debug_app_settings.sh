#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Load the private environment without evaluating it as shell code.
if [[ "${PERCLIP_ENV_LOADED:-}" != "1" ]]; then
  exec "$ROOT_DIR/scripts/with_env.sh" env PERCLIP_ENV_LOADED=1 bash "$0" "$@"
fi
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/_android_tools.sh"

ADB="$(require_adb)"
DEVICE_OUTPUT="$(select_device_arg "$ADB")"
DEVICE_ARG=()
while IFS= read -r arg; do
  DEVICE_ARG+=("$arg")
done <<< "$DEVICE_OUTPUT"

PACKAGE="${PERCLIP_APP_PACKAGE:-com.sudox.perclip.dev}"
API_URL="${PERCLIP_APP_API_URL:?Set PERCLIP_APP_API_URL in .env}"
TOKEN="${PERCLIP_APP_INGEST_TOKEN:-${PERCLIP_INGEST_TOKEN:?Set mobile token in .env}}"
DEVICE_NAME="${PERCLIP_APP_DEVICE_NAME:-Android Emulator PerClip}"
WIFI_ONLY="${PERCLIP_APP_WIFI_ONLY_LARGE_FILES:-true}"
PERSISTENT_QUICK_ENTRY="${PERCLIP_APP_PERSISTENT_QUICK_ENTRY:-false}"

xml_escape() {
  local value="$1"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  value="${value//\"/&quot;}"
  value="${value//\'/&apos;}"
  printf '%s' "$value"
}

require_boolean() {
  local name="$1"
  local value="$2"
  if [[ "$value" != "true" && "$value" != "false" ]]; then
    echo "${name} must be true or false." >&2
    exit 2
  fi
}

require_boolean "PERCLIP_APP_WIFI_ONLY_LARGE_FILES" "$WIFI_ONLY"
require_boolean "PERCLIP_APP_PERSISTENT_QUICK_ENTRY" "$PERSISTENT_QUICK_ENTRY"

if ! "$ADB" "${DEVICE_ARG[@]}" shell pm path "$PACKAGE" >/dev/null 2>&1; then
  echo "PerClip is not installed on the selected device. Run scripts/install_debug_apk.sh first." >&2
  exit 2
fi

if ! "$ADB" "${DEVICE_ARG[@]}" shell run-as "$PACKAGE" id >/dev/null 2>&1; then
  echo "Cannot access ${PACKAGE} with run-as. Install the debug APK before configuring settings." >&2
  exit 2
fi

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

cat > "$TMP_FILE" <<XML
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="api_url">$(xml_escape "$API_URL")</string>
    <string name="ingest_token">$(xml_escape "$TOKEN")</string>
    <string name="device_name">$(xml_escape "$DEVICE_NAME")</string>
    <boolean name="wifi_only_large_files" value="$WIFI_ONLY" />
    <boolean name="persistent_quick_entry" value="$PERSISTENT_QUICK_ENTRY" />
</map>
XML

"$ADB" "${DEVICE_ARG[@]}" shell \
  "run-as $PACKAGE sh -c 'mkdir -p shared_prefs && cat > shared_prefs/perclip_settings.xml'" < "$TMP_FILE"
"$ADB" "${DEVICE_ARG[@]}" shell am force-stop "$PACKAGE" >/dev/null

echo "Configured ${PACKAGE}:"
echo "  api_url:     ${API_URL}"
echo "  device_name: ${DEVICE_NAME}"
echo "  token:       $(printf '%s' "$TOKEN" | sed 's/./*/g')"
