#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
git -C "$repo_root" config core.hooksPath .githooks
chmod +x "$repo_root/.githooks/pre-commit" "$repo_root/.githooks/post-commit"

workspace_dir=$(CDPATH= cd -- "$repo_root/.." && pwd)
context_dir=${URSA_CONTEXT_DIR:-"$workspace_dir/Ursa_Context"}

printf '%s\n' "Configured Git hooks for $repo_root"
printf '%s\n' "core.hooksPath=.githooks"
if [ ! -f "$context_dir/tools/ursa_doc_guard.py" ]; then
  printf '%s\n' "Warning: Ursa_Context was not found at $context_dir" >&2
  printf '%s\n' "Set URSA_CONTEXT_DIR=/path/to/Ursa_Context before committing, or clone it next to this repo." >&2
fi

