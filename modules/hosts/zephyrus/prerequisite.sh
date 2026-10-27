#!/usr/bin/env bash
set -euo pipefail

if ! grep -Fqi 'ASUS' /sys/class/dmi/id/sys_vendor ||
    ! grep -Fq 'GA402RK' /sys/class/dmi/id/product_name; then
    echo 'The zephyrus host configuration requires an ASUS GA402RK.' >&2
    exit 1
fi
