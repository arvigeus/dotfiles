#!/usr/bin/env bash
set -Eeuo pipefail

update-mime-database /usr/local/share/mime
update-desktop-database /usr/local/share/applications
