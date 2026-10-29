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
sudo_environment=(DOTFILES_DIFF_EDITOR=meld)
for variable in DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS XAUTHORITY; do
    if [[ -n ${!variable:-} ]]; then
        sudo_environment+=("DOTFILES_DIFF_$variable=${!variable}")
    fi
done
exec sudo env "${sudo_environment[@]}" python3 \
    "$repo_dir/scripts/apply-config.py" "$repo_dir/user-configuration.json" "$@"
