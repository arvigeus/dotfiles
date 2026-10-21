#!/usr/bin/env bash
set -Eeuo pipefail

# Archinstall installs Dunst; the desktop shell owns org.freedesktop.Notifications.
if pacman -Q dunst >/dev/null 2>&1; then
    pacman -Rns --noconfirm dunst
fi
