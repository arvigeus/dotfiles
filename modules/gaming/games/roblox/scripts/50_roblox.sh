#!/usr/bin/env bash
set -Eeuo pipefail
# Sober reads controllers through raw input devices.
flatpak override --system --device=input org.vinegarhq.Sober
