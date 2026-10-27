#!/usr/bin/env bash
set -Eeuo pipefail
user=${1:?Username required}
if pgrep -u "$user" -x 'qbittorrent|qbittorrent-nox' > /dev/null; then
    echo 'Close qBittorrent before applying its configuration.' >&2
    exit 1
fi
user_home=$(getent passwd "$user" | cut -d: -f6)
[[ $user_home == /* && $user_home != / ]]
python3 "${DOTFILES_REPO:?}/modules/internet/qbittorrent/configure.py" \
    "$user_home/.config/qBittorrent/qBittorrent.conf" \
    "${XDG_CONFIG_HOME:?}/qBittorrent/qBittorrent.conf"
