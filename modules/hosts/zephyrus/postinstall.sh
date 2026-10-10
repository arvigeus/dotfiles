#!/usr/bin/env bash
set -euo pipefail

# asusd is a static unit, activated by its packaged udev rule, not enabled here.
if [[ ${DOTFILES_INSTALLING:-0} != 1 ]]; then
    systemctl restart asusd.service
fi
