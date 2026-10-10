#!/usr/bin/env bash
set -euo pipefail

user=${1:?Expected the account to configure}
usermod -aG wheel "$user"

visudo --check
