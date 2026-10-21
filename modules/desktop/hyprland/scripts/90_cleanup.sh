#!/usr/bin/env bash
set -Eeuo pipefail

# The console supervisor replaces the old manual desktop launcher.
rm -f /usr/local/bin/desktop-session

# Archinstall's Hyprland profile installs Wofi; Quickshell owns app search here.
# Remove Wofi and unused dependencies, retaining shared dependencies and checks.
if pacman -Q wofi >/dev/null 2>&1; then
    pacman -Rns --noconfirm wofi
fi
