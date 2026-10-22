#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run ./bootstrap.sh as root on the Arch ISO.' >&2; exit 1; }
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -f $repo_dir/user-configuration.json ]] || { echo 'Run ./generate-config.py first.' >&2; exit 1; }
bash "$repo_dir/scripts/configure.sh" --check
CONFIG_MODE=install bash "$repo_dir/scripts/configure.sh" --pre
exec archinstall --config "$repo_dir/user-configuration.json" --plugin "$repo_dir/scripts/copy-checkout.py" "$@"
