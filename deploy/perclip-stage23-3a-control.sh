#!/bin/sh
set -eu

CONFIG_FILE=/etc/perclip/perclip-stage23-3a-control.conf
SYSTEMD_DIR=/etc/systemd/system

fail() {
  printf 'stage23_3a_control=failed code=%s\n' "$1" >&2
  exit 1
}

[ "$(id -u)" -eq 0 ] || fail root_required
[ -f "$CONFIG_FILE" ] || fail config_missing
# shellcheck disable=SC1090
. "$CONFIG_FILE"

for name in \
  COMMIT_SHA IMAGE DOCKER_BIN SYSTEMCTL_BIN \
  CANDIDATE_ENV CANDIDATE_ENV_SHA INSTALLED_ENV \
  CANDIDATE_API_UNIT CANDIDATE_API_UNIT_SHA \
  CANDIDATE_WORKER_UNIT CANDIDATE_WORKER_UNIT_SHA \
  ROLLBACK_DIR
do
  eval "value=\${$name:-}"
  [ -n "$value" ] || fail "config_${name}_missing"
done

verify_file() {
  file=$1
  expected=$2
  [ -f "$file" ] || fail candidate_missing
  actual=$(sha256sum "$file" | awk '{print $1}')
  [ "$actual" = "$expected" ] || fail candidate_hash_mismatch
}

verify_candidate() {
  verify_file "$CANDIDATE_ENV" "$CANDIDATE_ENV_SHA"
  verify_file "$CANDIDATE_API_UNIT" "$CANDIDATE_API_UNIT_SHA"
  verify_file "$CANDIDATE_WORKER_UNIT" "$CANDIDATE_WORKER_UNIT_SHA"
  revision=$("$DOCKER_BIN" image inspect "$IMAGE" \
    --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  [ "$revision" = "$COMMIT_SHA" ] || fail image_revision_mismatch
}

service_value() {
  "$SYSTEMCTL_BIN" "$1" "$2.service" >/dev/null 2>&1
}

record_original_state() {
  install -d -m 0700 "$ROLLBACK_DIR"
  if [ ! -f "$ROLLBACK_DIR/recorded" ]; then
    ingest_fragment=$("$SYSTEMCTL_BIN" show perclip-ingest.service \
      -p FragmentPath --value)
    [ -n "$ingest_fragment" ] || fail original_ingest_unit_missing
    cp "$ingest_fragment" "$ROLLBACK_DIR/perclip-ingest.service"
    printf '%s\n' "$ingest_fragment" > "$ROLLBACK_DIR/ingest-fragment"
    "$SYSTEMCTL_BIN" is-enabled perclip-ingest.service \
      > "$ROLLBACK_DIR/ingest-enabled" 2>/dev/null || true
    "$SYSTEMCTL_BIN" is-active perclip-ingest.service \
      > "$ROLLBACK_DIR/ingest-active" 2>/dev/null || true

    worker_fragment=$("$SYSTEMCTL_BIN" show perclip-worker.service \
      -p FragmentPath --value 2>/dev/null || true)
    if [ -n "$worker_fragment" ]; then
      cp "$worker_fragment" "$ROLLBACK_DIR/perclip-worker.service"
      printf '%s\n' "$worker_fragment" > "$ROLLBACK_DIR/worker-fragment"
      printf '1\n' > "$ROLLBACK_DIR/worker-had-unit"
    else
      printf '0\n' > "$ROLLBACK_DIR/worker-had-unit"
    fi
    "$SYSTEMCTL_BIN" is-enabled perclip-worker.service \
      > "$ROLLBACK_DIR/worker-enabled" 2>/dev/null || true
    "$SYSTEMCTL_BIN" is-active perclip-worker.service \
      > "$ROLLBACK_DIR/worker-active" 2>/dev/null || true
    touch "$ROLLBACK_DIR/recorded"
    chmod 0600 "$ROLLBACK_DIR"/*
  fi
}

require_inactive() {
  service_value is-active perclip-ingest && fail ingest_still_active
  service_value is-active perclip-worker && fail worker_still_active
  return 0
}

case "${1:-}" in
  check)
    verify_candidate
    printf 'stage23_3a_control=ready candidate_hashes=ok image_revision=ok\n'
    ;;
  pause)
    verify_candidate
    record_original_state
    "$SYSTEMCTL_BIN" stop perclip-worker.service >/dev/null 2>&1 || true
    "$SYSTEMCTL_BIN" stop perclip-ingest.service
    require_inactive
    printf 'stage23_3a_control=paused api=inactive worker=inactive\n'
    ;;
  install-units)
    verify_candidate
    [ -f "$ROLLBACK_DIR/recorded" ] || fail original_state_not_recorded
    require_inactive
    install -d -m 0755 "$(dirname "$INSTALLED_ENV")"
    install -m 0600 -o root -g root "$CANDIDATE_ENV" "$INSTALLED_ENV"
    install -m 0644 -o root -g root \
      "$CANDIDATE_API_UNIT" "$SYSTEMD_DIR/perclip-ingest.service"
    install -m 0644 -o root -g root \
      "$CANDIDATE_WORKER_UNIT" "$SYSTEMD_DIR/perclip-worker.service"
    "$SYSTEMCTL_BIN" daemon-reload
    printf 'stage23_3a_control=installed units=2 env_mode=600\n'
    ;;
  start-candidate)
    verify_candidate
    "$SYSTEMCTL_BIN" enable perclip-ingest.service perclip-worker.service \
      >/dev/null
    "$SYSTEMCTL_BIN" start perclip-ingest.service
    "$SYSTEMCTL_BIN" start perclip-worker.service
    service_value is-active perclip-ingest || fail candidate_ingest_inactive
    service_value is-active perclip-worker || fail candidate_worker_inactive
    printf 'stage23_3a_control=started api=active worker=active\n'
    ;;
  stop-candidate)
    "$SYSTEMCTL_BIN" stop perclip-worker.service >/dev/null 2>&1 || true
    "$SYSTEMCTL_BIN" stop perclip-ingest.service >/dev/null 2>&1 || true
    require_inactive
    printf 'stage23_3a_control=stopped api=inactive worker=inactive\n'
    ;;
  rollback)
    [ -f "$ROLLBACK_DIR/recorded" ] || fail original_state_not_recorded
    "$SYSTEMCTL_BIN" stop perclip-worker.service >/dev/null 2>&1 || true
    "$SYSTEMCTL_BIN" stop perclip-ingest.service >/dev/null 2>&1 || true
    "$SYSTEMCTL_BIN" disable perclip-worker.service >/dev/null 2>&1 || true
    ingest_fragment=$(sed -n '1p' "$ROLLBACK_DIR/ingest-fragment")
    if [ "$ingest_fragment" != "$SYSTEMD_DIR/perclip-ingest.service" ]; then
      rm -f "$SYSTEMD_DIR/perclip-ingest.service"
    fi
    install -m 0644 -o root -g root \
      "$ROLLBACK_DIR/perclip-ingest.service" "$ingest_fragment"
    if [ "$(sed -n '1p' "$ROLLBACK_DIR/worker-had-unit")" = 1 ]; then
      worker_fragment=$(sed -n '1p' "$ROLLBACK_DIR/worker-fragment")
      if [ "$worker_fragment" != "$SYSTEMD_DIR/perclip-worker.service" ]; then
        rm -f "$SYSTEMD_DIR/perclip-worker.service"
      fi
      install -m 0644 -o root -g root \
        "$ROLLBACK_DIR/perclip-worker.service" "$worker_fragment"
    else
      rm -f "$SYSTEMD_DIR/perclip-worker.service"
    fi
    rm -f "$INSTALLED_ENV"
    "$SYSTEMCTL_BIN" daemon-reload
    if grep -qx enabled "$ROLLBACK_DIR/ingest-enabled"; then
      "$SYSTEMCTL_BIN" enable perclip-ingest.service >/dev/null
    fi
    if grep -qx active "$ROLLBACK_DIR/ingest-active"; then
      "$SYSTEMCTL_BIN" start perclip-ingest.service
    fi
    if [ "$(sed -n '1p' "$ROLLBACK_DIR/worker-had-unit")" = 1 ]; then
      if grep -qx enabled "$ROLLBACK_DIR/worker-enabled"; then
        "$SYSTEMCTL_BIN" enable perclip-worker.service >/dev/null
      fi
      if grep -qx active "$ROLLBACK_DIR/worker-active"; then
        "$SYSTEMCTL_BIN" start perclip-worker.service
      fi
    fi
    printf 'stage23_3a_control=rolled_back original_units=restored\n'
    ;;
  status)
    api=inactive
    worker=inactive
    service_value is-active perclip-ingest && api=active
    service_value is-active perclip-worker && worker=active
    printf 'stage23_3a_control=status api=%s worker=%s\n' "$api" "$worker"
    ;;
  *)
    fail unsupported_action
    ;;
esac
