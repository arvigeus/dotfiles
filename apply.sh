#!/usr/bin/env bash
set -euo pipefail
for argument in "$@"; do
    case $argument in
        --dry-run | --no-package-review | --help | -h) ;;
        *)
            echo 'Usage: ./apply.sh [--dry-run] [--no-package-review]' >&2
            exit 1
            ;;
    esac
done
[[ $EUID != 0 ]] || {
    echo 'Run ./apply.sh as your regular user.' >&2
    exit 1
}
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ " $* " != *' --dry-run '* && " $* " != *' --help '* && " $* " != *' -h '* ]]; then
    "$repo_dir/validate.sh"
fi
exec sudo python3 "$repo_dir/scripts/apply-config.py" "$repo_dir/user-configuration.json" "$@"
