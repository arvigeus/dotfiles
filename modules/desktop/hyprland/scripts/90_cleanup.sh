#!/usr/bin/env bash
set -Eeuo pipefail

# Archinstall's Hyprland profile installs Wofi; Quickshell owns app search here.
# Remove only Wofi, retaining shared dependencies and normal dependency checks.
if pacman -Q wofi >/dev/null 2>&1; then
    pacman -Rns --noconfirm wofi
fi
