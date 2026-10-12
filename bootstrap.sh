#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run ./bootstrap.sh as root on the Arch ISO.' >&2; exit 1; }
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -f $repo_dir/user-configuration.sh ]] || { echo 'Run ./generate-config.py first.' >&2; exit 1; }
CONFIG_MODE=live bash "$repo_dir/user-configuration.sh" --check
CONFIG_MODE=install bash "$repo_dir/user-configuration.sh" --pre
exec archinstall --config "$repo_dir/user-configuration.json" --plugin "$repo_dir/scripts/copy-checkout.py" "$@"
