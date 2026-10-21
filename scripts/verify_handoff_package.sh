#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PACKAGE_INPUT="${1:-}"
TMP_DIR=""

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"

cleanup() {
  if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

fail() {
  echo "FAIL  $1" >&2
  exit 1
}

pass() {
  echo "PASS  $1"
}

step() {
  printf '\n==> %s\n' "$1"
}

latest_zip() {
  find "$ROOT_DIR/dist" -maxdepth 1 -type f -name 'PerClip-handoff-*.zip' -print 2>/dev/null \
    | LC_ALL=C sort \
    | tail -n 1
}

resolve_package_dir() {
  local input="$1"

  if [[ -z "$input" ]]; then
    input="$(latest_zip)"
    [[ -n "$input" ]] || fail "No PerClip-handoff-*.zip found under dist/"
  fi

  if [[ -d "$input" ]]; then
    printf '%s\n' "$(cd "$input" && pwd)"
    return
  fi

  [[ -f "$input" ]] || fail "Package path does not exist: $input"
  case "$input" in
    *.zip) ;;
    *) fail "Package must be a directory or .zip file: $input" ;;
  esac

  TMP_DIR="$(mktemp -d -t perclip-handoff-verify.XXXXXX)"
  unzip -q "$input" -d "$TMP_DIR"

  local roots
  roots="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'PerClip-handoff-*' -print)"
  local count
  count="$(printf '%s\n' "$roots" | sed '/^$/d' | wc -l | tr -d ' ')"
  [[ "$count" == "1" ]] || fail "Expected exactly one PerClip-handoff-* root in zip, found $count"
  printf '%s\n' "$roots"
}

check_required_files() {
  local package_dir="$1"
  local required=(
    "apk/PerClip-debug.apk"
    "apk/output-metadata.json"
    "BUILD_INFO.txt"
    "ANDROID_SOURCE_MANIFEST.txt"
    "SHA256SUMS.txt"
    "android/gradlew"
    "android/settings.gradle.kts"
    "android/app/src/main/AndroidManifest.xml"
    "server/.env.example"
    "scripts/generate_mobile_token.sh"
    "scripts/audit_android_apk.sh"
  )

  local file
  for file in "${required[@]}"; do
    [[ -e "$package_dir/$file" ]] || fail "Missing required package file: $file"
  done
  [[ -x "$package_dir/android/gradlew" ]] || fail "android/gradlew is not executable"
  [[ -x "$package_dir/scripts/generate_mobile_token.sh" ]] || fail "scripts/generate_mobile_token.sh is not executable"
  pass "required files present"
}

check_checksums() {
  local package_dir="$1"
  (cd "$package_dir" && shasum -a 256 -c SHA256SUMS.txt)
  pass "SHA256SUMS.txt verified"

  (cd "$package_dir" && shasum -a 256 -c ANDROID_SOURCE_MANIFEST.txt >/dev/null)
  pass "ANDROID_SOURCE_MANIFEST.txt verified"
}

check_forbidden_files() {
  local package_dir="$1"
  local forbidden
  forbidden="$(
    find "$package_dir" \
      \( -path '*/android/.gradle/*' \
      -o -path '*/android/.kotlin/*' \
      -o -path '*/android/build/*' \
      -o -path '*/android/app/build/*' \
      -o -path '*/server/data/*' \
      -o -name 'local.properties' \
      -o -name '.env' \
      -o -name '__pycache__' \
      -o -name '.pytest_cache' \
      -o -name '*.pyc' \
      -o -name '*.egg-info' \
      -o -name '*.jks' \
      -o -name '*.keystore' \
      -o -name '*.pem' \
      -o -name '*.p12' \) \
      -print
  )"

  if [[ -n "$forbidden" ]]; then
    echo "$forbidden" >&2
    fail "Package contains forbidden cache, local config, data, or key files"
  fi
  pass "no forbidden cache, local config, data, or key files"
}

check_apk() {
  local package_dir="$1"
  "$package_dir/scripts/audit_android_apk.sh" "$package_dir/apk/PerClip-debug.apk"
  pass "APK audit verified"
}

check_build_info_matches_apk() {
  local package_dir="$1"
  local expected
  local actual
  expected="$(awk -F': ' '$1 == "apk_sha256" { print $2 }' "$package_dir/BUILD_INFO.txt")"
  actual="$(shasum -a 256 "$package_dir/apk/PerClip-debug.apk" | awk '{ print $1 }')"
  [[ -n "$expected" ]] || fail "BUILD_INFO.txt missing apk_sha256"
  [[ "$expected" == "$actual" ]] || fail "BUILD_INFO apk_sha256 does not match APK"
  pass "BUILD_INFO APK SHA matches"
}

maybe_rebuild_android() {
  local package_dir="$1"
  if [[ "${PERCLIP_VERIFY_REBUILD:-0}" != "1" ]]; then
    echo "SKIP  Android rebuild; set PERCLIP_VERIFY_REBUILD=1 to run Gradle tests/build/lint from packaged source"
    return
  fi

  (
    cd "$package_dir/android"
    ./gradlew testDebugUnitTest assembleDebug lintDebug
  )
  pass "packaged Android source rebuild verified"
}

PACKAGE_DIR="$(resolve_package_dir "$PACKAGE_INPUT")"
echo "Verifying handoff package: $PACKAGE_DIR"

step "Required files"
check_required_files "$PACKAGE_DIR"

step "Checksums"
check_checksums "$PACKAGE_DIR"

step "Forbidden files"
check_forbidden_files "$PACKAGE_DIR"

step "APK"
check_apk "$PACKAGE_DIR"
check_build_info_matches_apk "$PACKAGE_DIR"

step "Optional Android rebuild"
maybe_rebuild_android "$PACKAGE_DIR"

echo
echo "Handoff package verification passed."
