#!/usr/bin/env bash
set -Eeuo pipefail
# Bash does not create the directory of HISTFILE.
install -d -m 0755 "$HOME/.local/state/bash"
