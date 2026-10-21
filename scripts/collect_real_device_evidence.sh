#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/_android_tools.sh"

STAMP="${PERCLIP_EVIDENCE_STAMP:-$(date +%Y%m%d-%H%M%S)}"
REPORT_DIR="${PERCLIP_EVIDENCE_DIR:-$ROOT_DIR/dist/evidence}"
REPORT_PATH="${PERCLIP_EVIDENCE_PATH:-$REPORT_DIR/perclip-real-device-evidence-${STAMP}.md}"
PACKAGE="${PERCLIP_APP_PACKAGE:-com.sudox.perclip.dev}"
APK_PATH="$ROOT_DIR/android/app/build/outputs/apk/debug/app-debug.apk"
failures=0

mkdir -p "$(dirname "$REPORT_PATH")"

append() {
  printf '%s\n' "$*" >>"$REPORT_PATH"
}

append_block() {
  append '```text'
  if [[ -n "$1" ]]; then
    printf '%s\n' "$1" >>"$REPORT_PATH"
  fi
  append '```'
}

mark_failure() {
  failures=$((failures + 1))
}

run_section() {
  local title="$1"
  local display="$2"
  shift 2
  local output
  local exit_code

  append
  append "## ${title}"
  append
  append "command: \`${display}\`"
  append

  set +e
  output="$("$@" 2>&1)"
  exit_code=$?
  set -e

  append "exit_code: ${exit_code}"
  append_block "$output"

  if (( exit_code != 0 )); then
    mark_failure
  fi
}

write_header() {
  cat >"$REPORT_PATH" <<EOF
# PerClip Real Device Evidence

generated_at: ${STAMP}
workspace: ${ROOT_DIR}
package: ${PACKAGE}

This report is safe to share with the project. It records whether required
evidence was collected, but it does not print mobile tokens or RAGFlow API keys.
EOF
}

collect_apk_info() {
  append
  append "## APK"
  append

  if [[ ! -f "$APK_PATH" ]]; then
    append "status: missing"
    append "path: ${APK_PATH}"
    mark_failure
    return
  fi

  local size
  local sha
  size="$(wc -c <"$APK_PATH" | tr -d ' ')"
  sha="$(shasum -a 256 "$APK_PATH" | awk '{ print $1 }')"
  append "status: present"
  append "path: ${APK_PATH}"
  append "size_bytes: ${size}"
  append "sha256: ${sha}"
}

collect_device_info() {
  append
  append "## Android Device"
  append

  local adb_path
  if ! adb_path="$(require_adb 2>&1)"; then
    append "status: adb-missing"
    append_block "$adb_path"
    mark_failure
    return
  fi

  local device_output
  if ! device_output="$(select_device_arg "$adb_path" 2>&1)"; then
    append "status: no-authorized-device"
    append_block "$device_output"
    mark_failure
    return
  fi

  local device_arg=()
  while IFS= read -r arg; do
    device_arg+=("$arg")
  done <<< "$device_output"

  local serial
  local manufacturer
  local model
  local release
  local sdk
  serial="$("$adb_path" "${device_arg[@]}" get-serialno 2>/dev/null | tr -d '\r' || true)"
  manufacturer="$("$adb_path" "${device_arg[@]}" shell getprop ro.product.manufacturer 2>/dev/null | tr -d '\r' || true)"
  model="$("$adb_path" "${device_arg[@]}" shell getprop ro.product.model 2>/dev/null | tr -d '\r' || true)"
  release="$("$adb_path" "${device_arg[@]}" shell getprop ro.build.version.release 2>/dev/null | tr -d '\r' || true)"
  sdk="$("$adb_path" "${device_arg[@]}" shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r' || true)"

  append "status: authorized"
  append "serial: ${serial:-unknown}"
  append "manufacturer: ${manufacturer:-unknown}"
  append "model: ${model:-unknown}"
  append "android_release: ${release:-unknown}"
  append "android_sdk: ${sdk:-unknown}"

  append
  append "### Installed PerClip Package"
  append

  local package_info
  set +e
  package_info="$("$adb_path" "${device_arg[@]}" shell dumpsys package "$PACKAGE" 2>&1 | tr -d '\r' | grep -E 'versionName|versionCode|firstInstallTime|lastUpdateTime' || true)"
  set -e
  if [[ -n "$package_info" ]]; then
    append_block "$package_info"
  else
    append "status: not-installed-or-no-package-info"
    mark_failure
  fi
}

run_optional_smokes() {
  if [[ "${PERCLIP_RUN_DEVICE_SMOKES:-0}" == "1" ]]; then
    run_section "Entrypoint Smoke" "scripts/adb_entrypoint_smoke.sh" "$ROOT_DIR/scripts/adb_entrypoint_smoke.sh"
    run_section "Notification Entry Smoke" "scripts/adb_notification_entry_smoke.sh" "$ROOT_DIR/scripts/adb_notification_entry_smoke.sh"
    run_section "Quick Settings Tile Smoke" "scripts/adb_qs_tile_smoke.sh" "$ROOT_DIR/scripts/adb_qs_tile_smoke.sh"
    run_section "Clip Library Smoke" "scripts/adb_clip_library_smoke.sh" "$ROOT_DIR/scripts/adb_clip_library_smoke.sh"
  else
    append
    append "## Device Smoke Scripts"
    append
    append "status: skipped"
    append "reason: set \`PERCLIP_RUN_DEVICE_SMOKES=1\` to run entrypoint, notification, Quick Settings tile, and Clip Library smoke scripts."
  fi

  if [[ "${PERCLIP_RUN_SERVER_SMOKE:-0}" == "1" ]]; then
    if [[ -z "${PERCLIP_INGEST_TOKEN:-}" ]]; then
      append
      append "## Server Smoke"
      append
      append "status: skipped"
      append "reason: \`PERCLIP_RUN_SERVER_SMOKE=1\` requires \`PERCLIP_INGEST_TOKEN\` in the environment."
      mark_failure
    else
      run_section "Server Smoke" "PERCLIP_INGEST_TOKEN=<redacted> scripts/smoke_server.sh" "$ROOT_DIR/scripts/smoke_server.sh"
    fi
  else
    append
    append "## Server Smoke"
    append
    append "status: skipped"
    append "reason: set \`PERCLIP_RUN_SERVER_SMOKE=1\` with a running ingest API and \`PERCLIP_INGEST_TOKEN\` to collect server smoke evidence."
  fi
}

write_manual_template() {
  append
  append "## Manual Result Template"
  append
  append_block "coloros_version:
network_path: LAN | Tailscale
api_url:

share_url: pass | fail
share_text: pass | fail
share_image: pass | fail
share_pdf: pass | fail
share_multi_file: pass | fail
offline_retry: pass | fail
large_file_wifi_policy: pass | fail

sample_original_path:
sample_ragflow_document_id:
notes:"
}

write_header
collect_apk_info
run_section "APK Secret Audit" "scripts/audit_android_apk.sh" "$ROOT_DIR/scripts/audit_android_apk.sh"
collect_device_info
run_section "Readiness" "scripts/check_e2e_readiness.sh" "$ROOT_DIR/scripts/check_e2e_readiness.sh"
run_optional_smokes
write_manual_template

append
append "## Summary"
append
if (( failures == 0 )); then
  append "status: pass"
else
  append "status: incomplete"
  append "failure_count: ${failures}"
fi

printf 'Evidence report written: %s\n' "$REPORT_PATH"

if (( failures > 0 )) && [[ "${PERCLIP_EVIDENCE_ALLOW_FAILURES:-0}" != "1" ]]; then
  exit 1
fi
