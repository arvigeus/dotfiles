#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
bash "$repo_dir/scripts/storage-config.sh" /dev/nvme0n1 1023133351936
