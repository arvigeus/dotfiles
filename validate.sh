#!/usr/bin/env bash
set -euo pipefail
[[ $# == 0 ]] || { echo 'Usage: ./validate.sh' >&2; exit 1; }
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
command -v archinstall >/dev/null || {
    echo 'Install archinstall first: sudo pacman -Syu --needed archinstall' >&2; exit 1;
}
command=(archinstall --config "$repo_dir/user-configuration.json" --dry-run --silent --offline --skip-version-check)
if [[ $EUID == 0 ]]; then exec "${command[@]}"; fi
exec sudo "${command[@]}"
