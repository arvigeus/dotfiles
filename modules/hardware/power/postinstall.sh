#!/usr/bin/env bash
set -euo pipefail

if [[ ${DOTFILES_INSTALLING:-0} != 1 ]]; then
    systemctl try-restart tuned.service tuned-ppd.service
fi
