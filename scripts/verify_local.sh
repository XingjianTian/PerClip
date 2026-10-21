#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SKIP_ANDROID="${PERCLIP_VERIFY_SKIP_ANDROID:-false}"
SKIP_SERVER="${PERCLIP_VERIFY_SKIP_SERVER:-false}"
WITH_ASSEMBLE="${PERCLIP_VERIFY_WITH_ASSEMBLE:-false}"
WITH_SMOKE="${PERCLIP_VERIFY_WITH_SMOKE:-false}"

step() {
  printf '\n==> %s\n' "$1"
}

is_true() {
  [[ "$1" == "true" ]]
}

run_server_tests() {
  if is_true "$SKIP_SERVER"; then
    step "Skip server pytest (PERCLIP_VERIFY_SKIP_SERVER=true)"
    return
  fi

  step "Run server pytest"
  cd "$ROOT_DIR/server"
  uv run --extra dev pytest
}

run_android_tests() {
  if is_true "$SKIP_ANDROID"; then
    step "Skip Android JVM tests and lint (PERCLIP_VERIFY_SKIP_ANDROID=true)"
    return
  fi

  step "Run Android JVM tests"
  cd "$ROOT_DIR/android"
  ./gradlew :app:testDebugUnitTest

  step "Run Android lint"
  cd "$ROOT_DIR/android"
  ./gradlew :app:lintDebug

  if is_true "$WITH_ASSEMBLE"; then
    step "Run Android debug assemble (PERCLIP_VERIFY_WITH_ASSEMBLE=true)"
    cd "$ROOT_DIR/android"
    ./gradlew :app:assembleDebug
  fi
}

run_light_smoke_checks() {
  if ! is_true "$WITH_SMOKE"; then
    step "Skip server smoke checks (PERCLIP_VERIFY_WITH_SMOKE is not true)"
    return
  fi

  step "Check lightweight server smoke script syntax"
  cd "$ROOT_DIR"
  bash -n \
    scripts/smoke_server.sh \
    scripts/smoke_server_route_decision.sh \
    scripts/smoke_server_enrichment.sh \
    scripts/smoke_server_clip_move.sh
}

run_diff_check() {
  step "Run git diff whitespace check"
  cd "$ROOT_DIR"
  git diff --check
}

cd "$ROOT_DIR"
run_server_tests
run_android_tests
run_light_smoke_checks
run_diff_check

step "Local verification complete"
