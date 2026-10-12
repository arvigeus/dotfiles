#!/usr/bin/env bash
set -Eeuo pipefail
# Compile files/etc/dconf/db/local.d into the binary database read by Meld.
# Needed to compile changed keyfiles.
dconf update
