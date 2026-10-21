#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APK_PATH="${1:-$ROOT_DIR/android/app/build/outputs/apk/release/app-release-unsigned.apk}"
EXPECTED_PACKAGE="com.sudox.perclip"
EXPECTED_VERSION_CODE="3"
EXPECTED_VERSION_NAME="0.3.0"

fail() {
  echo "Release audit failed: $*" >&2
  exit 1
}

[[ -f "$APK_PATH" ]] || fail "APK not found: $APK_PATH"

SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
AAPT_PATH="$(find "$SDK_ROOT/build-tools" -type f -name aapt -perm -111 -print 2>/dev/null | sort -V | tail -n 1)"
[[ -n "$AAPT_PATH" ]] || fail "aapt was not found under $SDK_ROOT/build-tools"

BADGING="$($AAPT_PATH dump badging "$APK_PATH")"
EXPECTED_PACKAGE_LINE="package: name='$EXPECTED_PACKAGE' versionCode='$EXPECTED_VERSION_CODE' versionName='$EXPECTED_VERSION_NAME'"
grep -Fq "$EXPECTED_PACKAGE_LINE" <<<"$BADGING" ||
  fail "APK package/version does not match $EXPECTED_PACKAGE $EXPECTED_VERSION_NAME ($EXPECTED_VERSION_CODE)"
if grep -Fq "application-debuggable" <<<"$BADGING"; then
  fail "Release APK is marked debuggable"
fi

TMP_DIR="$(mktemp -d -t perclip-release-audit.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT
unzip -qq "$APK_PATH" -d "$TMP_DIR"

for marker in \
  "RecallEvidenceActivity" \
  "KnowledgeEvidenceActivity" \
  "SettingsEvidenceActivity" \
  "CapabilityEvidenceActivity" \
  "PerClipApi35BrandV2" \
  "Stage 23.4 Synthetic" \
  "Stage 23.8 Synthetic"; do
  if grep -aR -Fq -- "$marker" "$TMP_DIR"; then
    fail "debug-only fixture marker found in Release APK: $marker"
  fi
done

"$ROOT_DIR/scripts/audit_android_apk.sh" "$APK_PATH"
"$ROOT_DIR/scripts/audit_android_brand_icons.sh" "$APK_PATH"

APK_SHA256="$(shasum -a 256 "$APK_PATH" | awk '{print $1}')"
echo "Release audit passed: package=$EXPECTED_PACKAGE versionName=$EXPECTED_VERSION_NAME versionCode=$EXPECTED_VERSION_CODE"
echo "Release APK: ${APK_PATH#$ROOT_DIR/}"
echo "Release APK SHA-256: $APK_SHA256"
