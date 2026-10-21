#!/usr/bin/env bash
set -Eeuo pipefail

# Keep Blueman's manager available without starting its tray applet at login.
systemctl --global mask app-blueman@autostart.service
