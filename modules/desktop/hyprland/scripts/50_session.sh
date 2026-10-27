#!/usr/bin/env bash
set -Eeuo pipefail
repo_dir=${DOTFILES_REPO:?}
source "$repo_dir/scripts/config-helpers.sh"

[[ ${USERNAME:?} =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*\$?$ ]] || {
    echo 'Invalid autologin username.' >&2; exit 1;
}
file_write /etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF_CONFIG
[Service]
ExecStart=
ExecStart=-/usr/bin/agetty --autologin $USERNAME --noreset --noclear --noissue --skip-login - \${TERM}
EOF_CONFIG
# UWSM's may-start check requires the graphical target even without a greeter.
systemctl set-default graphical.target
