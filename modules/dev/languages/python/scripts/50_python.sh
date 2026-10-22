#!/usr/bin/env bash
set -Eeuo pipefail
# Python does not create the directory of PYTHON_HISTORY.
install -d -m 0755 "$HOME/.local/state/python"
