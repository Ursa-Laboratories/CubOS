#!/bin/sh
set -eu

config_dir="${CUBOS_CONFIG_DIR:-/var/lib/cub/configs}"
run_dir="${CUBOS_RUN_DIR:-/var/lib/cub/runs}"
data_path="${CUBOS_DATA_DB_PATH:-/var/lib/cub/data/cubos.db}"
data_dir="$(dirname "$data_path")"
gantry_log_dir="${CUBOS_GANTRY_LOG_DIR:-/var/lib/cub/logs/gantry}"

# A fresh bind-mounted volume masks the dirs baked into the image, so
# recreate them here before the app writes config, runs, data, or logs.
mkdir -p "$config_dir" "$run_dir" "$data_dir" "$gantry_log_dir"

if [ -z "$(find "$config_dir" -mindepth 1 -print -quit)" ]; then
    cp -R /opt/cubos/config-seed/. "$config_dir"/
fi

exec "$@"
