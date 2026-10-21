#!/bin/sh
set -eu

CONFIG_FILE=/etc/perclip/perclip-stage23-3b-control.conf
SYSTEMD_DIR=/etc/systemd/system

fail() {
  printf 'stage23_3b_control=failed code=%s\n' "$1" >&2
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
  CANDIDATE_OPERATOR_PROXY CANDIDATE_OPERATOR_PROXY_SHA \
  INSTALLED_OPERATOR_PROXY \
  CANDIDATE_OPERATOR_VERIFIER CANDIDATE_OPERATOR_VERIFIER_SHA \
  INSTALLED_OPERATOR_VERIFIER \
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

verify_unit_reference() {
  unit=$1
  reference=$2
  grep -F -- "$reference" "$unit" >/dev/null 2>&1 ||
    fail candidate_unit_reference_mismatch
}

verify_candidate() {
  verify_file "$CANDIDATE_ENV" "$CANDIDATE_ENV_SHA"
  verify_file "$CANDIDATE_API_UNIT" "$CANDIDATE_API_UNIT_SHA"
  verify_file "$CANDIDATE_WORKER_UNIT" "$CANDIDATE_WORKER_UNIT_SHA"
  verify_file "$CANDIDATE_OPERATOR_PROXY" "$CANDIDATE_OPERATOR_PROXY_SHA"
  verify_file "$CANDIDATE_OPERATOR_VERIFIER" \
    "$CANDIDATE_OPERATOR_VERIFIER_SHA"
  verify_unit_reference "$CANDIDATE_API_UNIT" \
    "--env-file $INSTALLED_ENV "
  verify_unit_reference "$CANDIDATE_API_UNIT" "$IMAGE "
  verify_unit_reference "$CANDIDATE_WORKER_UNIT" \
    "$INSTALLED_OPERATOR_PROXY --environment-file $INSTALLED_ENV "
  verify_unit_reference "$CANDIDATE_WORKER_UNIT" \
    "--verifier-script $INSTALLED_OPERATOR_VERIFIER "
  verify_unit_reference "$CANDIDATE_WORKER_UNIT" "$IMAGE "
  verify_unit_reference "$CANDIDATE_WORKER_UNIT" \
    "python -m tools.run_operator_verified_worker"
  revision=$("$DOCKER_BIN" image inspect "$IMAGE" \
    --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  [ "$revision" = "$COMMIT_SHA" ] || fail image_revision_mismatch
}

service_value() {
  "$SYSTEMCTL_BIN" "$1" "$2.service" >/dev/null 2>&1
}

record_file() {
  source=$1
  label=$2
  if [ -f "$source" ]; then
    cp "$source" "$ROLLBACK_DIR/$label"
    printf '1\n' > "$ROLLBACK_DIR/$label.exists"
  else
    printf '0\n' > "$ROLLBACK_DIR/$label.exists"
  fi
}

restore_file() {
  destination=$1
  label=$2
  mode=$3
  if [ "$(sed -n '1p' "$ROLLBACK_DIR/$label.exists")" = 1 ]; then
    install -m "$mode" -o root -g root \
      "$ROLLBACK_DIR/$label" "$destination"
  else
    rm -f "$destination"
  fi
}

record_original_state() {
  install -d -m 0700 "$ROLLBACK_DIR"
  if [ ! -f "$ROLLBACK_DIR/recorded" ]; then
    for service in perclip-ingest perclip-worker
    do
      fragment=$("$SYSTEMCTL_BIN" show "$service.service" \
        -p FragmentPath --value)
      [ -n "$fragment" ] || fail "original_${service}_unit_missing"
      cp "$fragment" "$ROLLBACK_DIR/$service.service"
      printf '%s\n' "$fragment" > "$ROLLBACK_DIR/$service.fragment"
      "$SYSTEMCTL_BIN" is-enabled "$service.service" \
        > "$ROLLBACK_DIR/$service.enabled" 2>/dev/null || true
      "$SYSTEMCTL_BIN" is-active "$service.service" \
        > "$ROLLBACK_DIR/$service.active" 2>/dev/null || true
    done
    record_file "$INSTALLED_ENV" installed.env
    record_file "$INSTALLED_OPERATOR_PROXY" operator-proxy.py
    record_file "$INSTALLED_OPERATOR_VERIFIER" operator-verifier.py
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
    printf 'stage23_3b_control=ready candidate_hashes=ok image_revision=ok\n'
    ;;
  pause)
    verify_candidate
    record_original_state
    "$SYSTEMCTL_BIN" stop perclip-worker.service >/dev/null 2>&1 || true
    "$SYSTEMCTL_BIN" stop perclip-ingest.service
    require_inactive
    printf 'stage23_3b_control=paused api=inactive worker=inactive\n'
    ;;
  install-units)
    verify_candidate
    [ -f "$ROLLBACK_DIR/recorded" ] || fail original_state_not_recorded
    require_inactive
    install -d -m 0755 "$(dirname "$INSTALLED_ENV")"
    install -d -m 0755 "$(dirname "$INSTALLED_OPERATOR_PROXY")"
    install -m 0600 -o root -g root "$CANDIDATE_ENV" "$INSTALLED_ENV"
    install -m 0755 -o root -g root \
      "$CANDIDATE_OPERATOR_PROXY" "$INSTALLED_OPERATOR_PROXY"
    install -m 0644 -o root -g root \
      "$CANDIDATE_OPERATOR_VERIFIER" "$INSTALLED_OPERATOR_VERIFIER"
    install -m 0644 -o root -g root \
      "$CANDIDATE_API_UNIT" "$SYSTEMD_DIR/perclip-ingest.service"
    install -m 0644 -o root -g root \
      "$CANDIDATE_WORKER_UNIT" "$SYSTEMD_DIR/perclip-worker.service"
    "$SYSTEMCTL_BIN" daemon-reload
    printf 'stage23_3b_control=installed units=2 env_mode=600 verifier=ready\n'
    ;;
  start-candidate)
    verify_candidate
    "$SYSTEMCTL_BIN" enable perclip-ingest.service perclip-worker.service \
      >/dev/null
    "$SYSTEMCTL_BIN" start perclip-ingest.service
    "$SYSTEMCTL_BIN" start perclip-worker.service
    service_value is-active perclip-ingest || fail candidate_ingest_inactive
    service_value is-active perclip-worker || fail candidate_worker_inactive
    printf 'stage23_3b_control=started api=active worker=active\n'
    ;;
  stop-candidate)
    "$SYSTEMCTL_BIN" stop perclip-worker.service >/dev/null 2>&1 || true
    "$SYSTEMCTL_BIN" stop perclip-ingest.service >/dev/null 2>&1 || true
    require_inactive
    printf 'stage23_3b_control=stopped api=inactive worker=inactive\n'
    ;;
  rollback)
    [ -f "$ROLLBACK_DIR/recorded" ] || fail original_state_not_recorded
    "$SYSTEMCTL_BIN" stop perclip-worker.service >/dev/null 2>&1 || true
    "$SYSTEMCTL_BIN" stop perclip-ingest.service >/dev/null 2>&1 || true
    for service in perclip-ingest perclip-worker
    do
      fragment=$(sed -n '1p' "$ROLLBACK_DIR/$service.fragment")
      [ -n "$fragment" ] || fail "rollback_${service}_fragment_missing"
      if [ "$fragment" != "$SYSTEMD_DIR/$service.service" ]; then
        rm -f "$SYSTEMD_DIR/$service.service"
      fi
      install -m 0644 -o root -g root \
        "$ROLLBACK_DIR/$service.service" "$fragment"
    done
    restore_file "$INSTALLED_ENV" installed.env 0600
    restore_file "$INSTALLED_OPERATOR_PROXY" operator-proxy.py 0755
    restore_file "$INSTALLED_OPERATOR_VERIFIER" operator-verifier.py 0644
    "$SYSTEMCTL_BIN" daemon-reload
    for service in perclip-ingest perclip-worker
    do
      if grep -qx enabled "$ROLLBACK_DIR/$service.enabled"; then
        "$SYSTEMCTL_BIN" enable "$service.service" >/dev/null
      fi
      if grep -qx active "$ROLLBACK_DIR/$service.active"; then
        "$SYSTEMCTL_BIN" start "$service.service"
      fi
    done
    printf 'stage23_3b_control=rolled_back stage23_3a_units=restored\n'
    ;;
  status)
    api=inactive
    worker=inactive
    service_value is-active perclip-ingest && api=active
    service_value is-active perclip-worker && worker=active
    printf 'stage23_3b_control=status api=%s worker=%s\n' "$api" "$worker"
    ;;
  *)
    fail unsupported_action
    ;;
esac
