#!/usr/bin/env bash
# CubOS appliance updater. Exit codes: 0 update succeeded; 1 update failed and
# rollback succeeded; 2 rollback failed (manual recovery required); 3 another
# update holds the lock; 64 usage error.
# -E (errtrace) is load-bearing: without it the ERR trap does not fire for
# failures inside functions, and a failed install would skip rollback.
set -Eeuo pipefail

timestamp() {
  date '+%Y-%m-%dT%H:%M:%S%z'
}

log() {
  printf '%s\n' "$*"
}

# Prefix both our progress messages and child-process output before systemd
# captures the stream.
exec > >(
  while IFS= read -r line; do
    printf '%s %s\n' "$(timestamp)" "$line"
  done
) 2>&1

if [[ $# -ne 1 ]]; then
  log "usage: $0 <target-sha>"
  exit 64
fi

TARGET_SHA="$1"
CUBOS_REPO="${CUBOS_REPO:-/home/cub/CubOS}"
CUBOS_VENV="${CUBOS_VENV:-$CUBOS_REPO/.venv}"
CUBOS_SERVICE="${CUBOS_SERVICE:-cubos}"
CUBOS_HEALTH_URL="${CUBOS_HEALTH_URL:-http://127.0.0.1:8742/api/v1/health}"
CUBOS_HEALTH_ATTEMPTS="${CUBOS_HEALTH_ATTEMPTS:-30}"
CUBOS_HEALTH_INTERVAL="${CUBOS_HEALTH_INTERVAL:-2}"
LOCK_DIR="$CUBOS_REPO/.cubos-update.lock"
LOCK_HELD=0
PREV_SHA=""
ROLLBACK_READY=0
NEED_FRONTEND_BUILD=0

# One update at a time: the systemd path is already serialized by the unit
# name, but the dev fallback (and manual invocations) would otherwise race
# each other in the working tree. A dead holder's lock is treated as stale.
acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_HELD=1
    echo $$ > "$LOCK_DIR/pid"
    return 0
  fi
  local holder
  holder="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ -n "$holder" ]] && kill -0 "$holder" 2>/dev/null; then
    return 1
  fi
  log "Removing stale update lock left by pid ${holder:-unknown}"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" 2>/dev/null || return 1
  LOCK_HELD=1
  echo $$ > "$LOCK_DIR/pid"
}

release_lock() {
  if [[ "$LOCK_HELD" -eq 1 ]]; then
    rm -rf "$LOCK_DIR"
  fi
}
trap release_lock EXIT

install_cubos() {
  log "Installing CubOS packages into $CUBOS_VENV"
  "$CUBOS_VENV/bin/pip" install -e packages/core -e services/api
}

build_frontend() {
  log "Installing frontend dependencies and building"
  (
    cd apps/operator-web
    npm ci
    npm run build
  )
}

restart_cubos() {
  log "Restarting systemd service $CUBOS_SERVICE"
  sudo systemctl restart "$CUBOS_SERVICE"
}

wait_for_health() {
  local attempt
  for attempt in $(seq 1 "$CUBOS_HEALTH_ATTEMPTS"); do
    if curl --fail --silent --show-error "$CUBOS_HEALTH_URL" >/dev/null; then
      return 0
    fi
    log "Health check attempt $attempt/$CUBOS_HEALTH_ATTEMPTS failed; retrying in ${CUBOS_HEALTH_INTERVAL}s"
    sleep "$CUBOS_HEALTH_INTERVAL"
  done
  return 1
}

rollback() {
  local exit_code="${1:-1}"
  trap - ERR
  set +e
  log "Update to $TARGET_SHA failed with exit code $exit_code; rolling back to $PREV_SHA"
  local recovery_failed=0
  git checkout --detach "$PREV_SHA" || recovery_failed=1
  install_cubos || recovery_failed=1
  if [[ "$NEED_FRONTEND_BUILD" -eq 1 ]]; then
    build_frontend || recovery_failed=1
  fi
  restart_cubos || recovery_failed=1
  if [[ "$recovery_failed" -eq 0 ]] && wait_for_health; then
    log "Update failed; rollback to $PREV_SHA completed and CubOS is healthy"
    exit 1
  fi
  log "ROLLBACK FAILED: CubOS may be down at revision $(git rev-parse HEAD 2>/dev/null || echo unknown); manual recovery required — see deploy/pi/README.md"
  exit 2
}

# $? must be captured before any other command runs, or the trap would report
# the [[ ]] test's status instead of the failing command's.
trap 'rc=$?; if [[ "$ROLLBACK_READY" -eq 1 ]]; then rollback "$rc"; fi' ERR

log "Changing to repository $CUBOS_REPO"
cd "$CUBOS_REPO"

if ! acquire_lock; then
  log "Another update is already in progress (lock: $LOCK_DIR); aborting"
  exit 3
fi

PREV_SHA="$(git rev-parse HEAD)"
log "Current revision is $PREV_SHA; requested revision is $TARGET_SHA"

log "Fetching origin"
git fetch origin
log "Checking out $TARGET_SHA in detached mode"
git checkout --detach "$TARGET_SHA"
ROLLBACK_READY=1

if git diff --name-only "$PREV_SHA" "$TARGET_SHA" | grep -q '^apps/operator-web/'; then
  if command -v npm >/dev/null 2>&1; then
    NEED_FRONTEND_BUILD=1
  else
    log "WARNING: Operator UI changed but npm is unavailable; continuing without a frontend build"
  fi
fi

install_cubos
if [[ "$NEED_FRONTEND_BUILD" -eq 1 ]]; then
  build_frontend
fi
restart_cubos

log "Waiting up to $((CUBOS_HEALTH_ATTEMPTS * CUBOS_HEALTH_INTERVAL)) seconds for $CUBOS_HEALTH_URL"
if wait_for_health; then
  trap - ERR
  log "Update to $TARGET_SHA succeeded and CubOS is healthy"
  exit 0
fi

rollback 1
