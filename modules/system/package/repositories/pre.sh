#!/usr/bin/env bash
set -Eeuo pipefail
# Prepare trust before native repository transactions, on both ISO and target.
pacman-key --init
# ogc (Ayush Mukherjee) and chaotic-aur (Pedro Henrique Lara Campos)
for key in \
    F79100EF8C802DAB81C323BB8EEA5962FE510E19 \
    EF925EA60F33D0CB85C44AD13056513887B78AEB; do
    if ! pacman-key --list-keys "$key" >/dev/null 2>&1; then
        pacman-key --recv-keys "$key" --keyserver keyserver.ubuntu.com
    fi
    pacman-key --lsign-key "$key"
done
if ! pacman -Q chaotic-keyring chaotic-mirrorlist >/dev/null 2>&1; then
    pacman -U --needed --noconfirm -- \
        https://cdn-mirror.chaotic.cx/chaotic-aur/chaotic-keyring.pkg.tar.zst \
        https://cdn-mirror.chaotic.cx/chaotic-aur/chaotic-mirrorlist.pkg.tar.zst
fi
pacman-key --populate chaotic
