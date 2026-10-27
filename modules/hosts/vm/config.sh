#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
saved="$repo_dir/user-configuration.json"
if [[ ${1:-} != --configure && -f $saved ]] &&
    jq -e '.hostname == "vm" and (.disk_config.device_modifications | length) == 1' "$saved" >/dev/null; then
    device=$(jq -r '.disk_config.device_modifications[0].device' "$saved")
    size=$(jq -r '.disk_config.device_modifications[0].partitions[1].size.value' "$saved")
else
    read -r -p 'VM disk to wipe [/dev/vda]: ' device
    device=${device:-/dev/vda}
    read -r -p 'VM disk capacity in GiB (minimum 52): ' capacity
    if [[ ! $capacity =~ ^[1-9][0-9]{0,5}$ ]] || ((capacity < 52)); then
        echo 'Expected a disk capacity of at least 52 GiB.' >&2
        exit 1
    fi
    # Reserve the shared 1 GiB ESP, initial alignment, and room for the backup GPT.
    size=$((capacity * 1024**3 - 1074790400 - 1024**2))
fi
bash "$repo_dir/scripts/storage-config.sh" "$device" "$size"
