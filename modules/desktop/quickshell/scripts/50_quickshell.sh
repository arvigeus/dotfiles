#!/usr/bin/env bash
set -Eeuo pipefail

systemctl --global enable desktop-shell.service
systemctl --global enable desktop-capture.socket
systemctl --global enable cliphist@text.service cliphist@image.service
