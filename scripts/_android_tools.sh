#!/usr/bin/env bash

find_adb() {
  if command -v adb >/dev/null 2>&1; then
    command -v adb
    return 0
  fi

  local candidates=(
    "${ANDROID_HOME:-}/platform-tools/adb"
    "${ANDROID_SDK_ROOT:-}/platform-tools/adb"
    "$HOME/Library/Android/sdk/platform-tools/adb"
    "/opt/homebrew/share/android-commandlinetools/platform-tools/adb"
  )

  local adb_path
  for adb_path in "${candidates[@]}"; do
    if [[ -x "$adb_path" ]]; then
      printf '%s\n' "$adb_path"
      return 0
    fi
  done

  return 1
}

require_adb() {
  local adb_path
  if ! adb_path="$(find_adb)"; then
    echo "adb was not found. Install Android SDK platform-tools or add it to PATH." >&2
    echo "Common PATH entry: export PATH=\"\$HOME/Library/Android/sdk/platform-tools:\$PATH\"" >&2
    return 127
  fi
  printf '%s\n' "$adb_path"
}

select_device_arg() {
  local adb_path="$1"
  if [[ -n "${ANDROID_SERIAL:-}" ]]; then
    printf -- '-s\n%s\n' "$ANDROID_SERIAL"
    return 0
  fi

  local serial
  serial="$("$adb_path" devices | sed -n 's/[[:space:]]*device$//p' | sed -n '1p')"
  if [[ -z "$serial" ]]; then
    echo "No authorized Android device is connected." >&2
    echo "Enable USB debugging, connect the phone, accept the RSA prompt, then rerun." >&2
    return 2
  fi

  printf -- '-s\n%s\n' "$serial"
}

resolve_main_component() {
  local package="$1"
  local adb_path="$2"
  shift 2

  local component
  component="$("$adb_path" "$@" shell cmd package resolve-activity --brief "$package" 2>/dev/null \
    | tr -d '\r' \
    | awk 'index($0, "/") { resolved=$0 } END { if (resolved != "") print resolved }')"

  if [[ -z "$component" ]]; then
    echo "Could not resolve the launcher activity for ${package}." >&2
    return 2
  fi

  printf '%s\n' "$component"
}
