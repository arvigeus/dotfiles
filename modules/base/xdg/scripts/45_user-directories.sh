#!/usr/bin/env bash
set -Eeuo pipefail

# HOME points at the staging home; publication creates these as the regular user.
# Declaring user-dirs.dirs alone does not create folders before Dolphin starts.
# shellcheck source=modules/base/xdg/files/home/.config/user-dirs.dirs
source "${XDG_CONFIG_HOME:?}/user-dirs.dirs"
for variable in ${!XDG_@}; do
    [[ $variable == XDG_*_DIR ]] || continue
    mkdir -p -- "${!variable}"
done
