#!/usr/bin/env bash
set -Eeuo pipefail

# Keep the connection editor available without starting its tray applet at login.
systemctl --global mask 'app-nm\x2dapplet@autostart.service'
