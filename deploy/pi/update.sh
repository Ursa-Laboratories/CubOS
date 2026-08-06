#!/usr/bin/env bash
set -euo pipefail

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
  exit 2
fi

TARGET_SHA="$1"
CUBOS_REPO="${CUBOS_REPO:-/home/cub/CubOS}"
CUBOS_VENV="${CUBOS_VENV:-$CUBOS_REPO/.venv}"
CUBOS_SERVICE="${CUBOS_SERVICE:-cubos}"
CUBOS_HEALTH_URL="${CUBOS_HEALTH_URL:-http://127.0.0.1:8742/api/v1/health}"
PREV_SHA=""
ROLLBACK_READY=0

install_cubos() {
  log "Installing CubOS packages into $CUBOS_VENV"
  "$CUBOS_VENV/bin/pip" install -e packages/core -e services/api
}

restart_cubos() {
  log "Restarting systemd service $CUBOS_SERVICE"
  sudo systemctl restart "$CUBOS_SERVICE"
}

rollback() {
  local exit_code="${1:-1}"
  trap - ERR
  set +e
  log "Update to $TARGET_SHA failed with exit code $exit_code; rolling back to $PREV_SHA"
  git checkout --detach "$PREV_SHA"
  install_cubos
  restart_cubos
  log "Update failed; rollback to $PREV_SHA completed"
  exit 1
}

trap 'if [[ "$ROLLBACK_READY" -eq 1 ]]; then rollback "$?"; fi' ERR

log "Changing to repository $CUBOS_REPO"
cd "$CUBOS_REPO"
PREV_SHA="$(git rev-parse HEAD)"
log "Current revision is $PREV_SHA; requested revision is $TARGET_SHA"

log "Fetching origin"
git fetch origin
log "Checking out $TARGET_SHA in detached mode"
git checkout --detach "$TARGET_SHA"
ROLLBACK_READY=1

install_cubos

if git diff --name-only "$PREV_SHA" "$TARGET_SHA" | grep -q '^apps/operator-web/'; then
  if command -v npm >/dev/null 2>&1; then
    log "Operator UI changed; installing frontend dependencies and building"
    (
      cd apps/operator-web
      npm ci
      npm run build
    )
  else
    log "WARNING: Operator UI changed but npm is unavailable; continuing without a frontend build"
  fi
fi

restart_cubos

log "Waiting up to 60 seconds for $CUBOS_HEALTH_URL"
for attempt in {1..30}; do
  if curl --fail --silent --show-error "$CUBOS_HEALTH_URL" >/dev/null; then
    ROLLBACK_READY=0
    trap - ERR
    log "Update to $TARGET_SHA succeeded and CubOS is healthy"
    exit 0
  fi
  log "Health check attempt $attempt/30 failed; retrying in 2 seconds"
  sleep 2
done

rollback 1
