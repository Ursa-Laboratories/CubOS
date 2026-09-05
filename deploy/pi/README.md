# CubOS Pi in-app updates

By default (`CUBOS_UPDATE_MODE=tag`) the Operator UI checks for the most
recently tagged CubOS release (calver, e.g. `v2026.08.10`) rather than
tracking `origin/main` HEAD directly — merging to `main` is not the same as
releasing to appliances. Release tags are cut by the
`.github/workflows/weekly-release.yml` scheduled workflow (Sundays), which
skips quiet weeks with no new commits. Set `CUBOS_UPDATE_MODE=branch` to fall
back to tracking `origin/main` HEAD directly (useful for development).

When an operator chooses **Update & restart**, the API launches `update.sh` as a detached
`cubos-update` systemd unit running as the service user (`cub`), never as
root — repo code (git checkout, pip build hooks, npm scripts) must not
execute with elevated privileges. Root is borrowed only for the single
`systemctl restart cubos` command via its own sudoers entry.
The script checks out the requested revision,
reinstalls the editable CubOS packages, rebuilds the Operator UI when needed,
restarts CubOS, and verifies API health. A failed install, build, restart, or
health check rolls the checkout, Python packages, and (when it changed)
Operator UI bundle back to the previous revision, then re-verifies health.

Updater exit codes, visible in the journal: `0` update succeeded, `1` update
failed and rollback succeeded, `2` rollback failed (manual recovery required),
`3` another update already holds the lock, `64` usage error. A lock in the
repo (`.cubos-update.lock`) serializes updates; a lock left by a dead process
is reclaimed automatically.

## Assumptions

The default appliance layout is:

- repository: `/home/cub/CubOS`
- Python virtual environment: `/home/cub/CubOS/.venv`
- systemd service: `cubos`
- API health endpoint: `http://127.0.0.1:8742/api/v1/health`

The checkout must have an `origin` remote, and the `cub` user must be able to
fetch it without an interactive prompt. `git`, `curl`, and the virtual
environment's `pip` must be installed. `npm` is optional; when it is absent, a
frontend change is logged and the backend update continues.

## One-time setup

From the CubOS checkout:

```bash
chmod +x deploy/pi/update.sh
sudo install -o root -g root -m 0440 deploy/pi/cubos-update.sudoers /etc/sudoers.d/cubos-update
sudo visudo -cf /etc/sudoers.d/cubos-update
```

The API service supports these settings through its environment:

```ini
CUBOS_UPDATE_MODE=tag
CUBOS_UPDATE_BRANCH=main
CUBOS_UPDATE_REPO_DIR=/home/cub/CubOS
CUBOS_UPDATE_SCRIPT=/home/cub/CubOS/deploy/pi/update.sh
CUBOS_UPDATE_SERVICE=cubos
```

`CUBOS_UPDATE_BRANCH` only matters in `branch` mode; `tag` mode always
resolves the latest tag regardless of branch.

For a non-default script invocation, `update.sh` also accepts
`CUBOS_REPO`, `CUBOS_VENV`, `CUBOS_SERVICE`, and `CUBOS_HEALTH_URL`. Update the
absolute paths and service name in `cubos-update.sudoers` as well; sudo command
matching is exact. The `--uid=cub` value must name the account the CubOS
service runs as (the API passes its own user). Validate the edited file with
`visudo` before installing it.

After changing the API service environment, reload systemd and restart CubOS:

```bash
sudo systemctl daemon-reload
sudo systemctl restart cubos
```

## Watching an update

The updater writes timestamped progress to its transient systemd unit:

```bash
journalctl -u cubos-update -f
```

On a development machine without `systemd-run`, the API launches the script in
a detached session and appends output to `~/.cubos/update.log`.

## Manual rollback

Find the last known-good revision — in `tag` mode the update banner and
journal name release tags (e.g. `v2026.08.03`) rather than raw SHAs; a tag
name works anywhere a SHA does below — then run:

```bash
cd /home/cub/CubOS
git checkout --detach <previous-tag-or-sha>
/home/cub/CubOS/.venv/bin/pip install -e packages/core -e services/api
sudo systemctl restart cubos
curl --fail http://127.0.0.1:8742/api/v1/health
```

If the rolled-back revision changed `apps/operator-web/`, rebuild that checkout
with `npm ci && npm run build` from `apps/operator-web` before restarting the
service.
