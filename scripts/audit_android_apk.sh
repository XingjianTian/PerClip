#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APK_PATH="${1:-$ROOT_DIR/android/app/build/outputs/apk/debug/app-debug.apk}"

if [[ ! -f "$APK_PATH" ]]; then
  echo "Debug APK not found, building it first."
  (cd "$ROOT_DIR/android" && ./gradlew assembleDebug)
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

unzip -qq "$APK_PATH" -d "$TMP_DIR"

forbidden_markers=(
  "RAGFLOW_API_KEY"
  "PERSONAL_CLIPS_DATASET_ID"
  "RAGFLOW_DATASET_ID"
  "change-me-server-side-ragflow-key"
  "change-me-dataset-id"
  "http://ragflow.internal:18080"
)

found=0
for marker in "${forbidden_markers[@]}"; do
  if LC_ALL=C grep -aR --fixed-strings --quiet -- "$marker" "$TMP_DIR"; then
    echo "Forbidden server-side marker found in APK: $marker" >&2
    found=1
  fi
done

if (( found > 0 )); then
  echo "APK audit failed: remove server-side RAGFlow config from the Android app." >&2
  exit 1
fi

echo "APK audit passed: no server-side RAGFlow secret markers found."
