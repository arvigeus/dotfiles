#!/usr/bin/env bash
set -Eeuo pipefail
# Select mirrors on the ISO; the target inherits this list through pacstrap.
# The installed system refreshes its list through reflector.timer.
[[ ${CONFIG_MODE:-install} == install && -d /run/archiso ]] || exit 0
reflector @"${MODULE_DIR:?}/files/etc/xdg/reflector/reflector.conf"
