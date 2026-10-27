#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if command -v system-agent >/dev/null 2>&1; then
    exec system-agent --dotfiles "$repo_dir" backup -- "$@"
fi
exec python3 "$repo_dir/scripts/private_files.py" backup --config "$repo_dir/user-configuration.json" "$@"
