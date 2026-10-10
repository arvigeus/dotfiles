#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

command -v archinstall >/dev/null || {
    echo 'archinstall is required; run this from the Arch Linux ISO.' >&2
    exit 1
}

"$repo_dir/generate-config.py"
exec archinstall --config "$repo_dir/user-configuration.json" "$@"
