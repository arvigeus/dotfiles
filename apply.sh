#!/usr/bin/env bash
set -euo pipefail

[[ $# == 0 ]] || { echo 'Usage: ./apply.sh' >&2; exit 1; }
[[ $EUID != 0 ]] || { echo 'Run ./apply.sh as your regular user.' >&2; exit 1; }
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
sudo bash "$repo_dir/scripts/apply-system.sh"
"$repo_dir/scripts/link-home.sh"
