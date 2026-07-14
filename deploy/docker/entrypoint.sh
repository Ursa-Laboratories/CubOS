#!/bin/sh
set -eu

config_dir="${CUBOS_CONFIG_DIR:-/var/lib/cub/configs}"
run_dir="${CUBOS_RUN_DIR:-/var/lib/cub/runs}"
data_path="${CUBOS_DATA_DB_PATH:-/var/lib/cub/data/cubos.db}"
data_dir="$(dirname "$data_path")"

mkdir -p "$config_dir" "$run_dir" "$data_dir"

if [ -z "$(find "$config_dir" -mindepth 1 -print -quit)" ]; then
    cp -R /opt/cubos/config-seed/. "$config_dir"/
fi

exec "$@"
