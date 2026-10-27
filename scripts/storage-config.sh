#!/usr/bin/env bash
set -euo pipefail

device=${1:?Expected disk device}
size=${2:?Expected LUKS partition size in bytes}
[[ $device =~ ^/dev/[a-zA-Z0-9/_-]+$ && $size =~ ^[1-9][0-9]{0,14}$ ]] || {
    echo 'Invalid disk device or partition size.' >&2
    exit 1
}
# The shared root LV needs 50 GiB; partition lengths must be MiB-aligned.
((size > 50 * 1024 ** 3 && size % (1024 ** 2) == 0)) || {
    echo 'The LUKS partition must exceed 50 GiB and be aligned to 1 MiB.' >&2
    exit 1
}
jq --arg device "$device" --argjson size "$size" '
    .disk_config.device_modifications[0].device = $device |
    .disk_config.device_modifications[0].partitions[1].size.value = $size
' << 'JSON'
{
    "disk_config": {
        "btrfs_options": {
            "snapshot_config": {
                "type": "Snapper"
            }
        },
        "config_type": "default_layout",
        "device_modifications": [
            {
                "device": null,
                "partitions": [
                    {
                        "btrfs": [],
                        "dev_path": null,
                        "flags": [
                            "boot",
                            "esp"
                        ],
                        "fs_type": "fat32",
                        "mount_options": [],
                        "mountpoint": "/boot",
                        "obj_id": "8e2bb495-1145-4bb6-83fe-00871f2312fc",
                        "size": {
                            "sector_size": {
                                "unit": "B",
                                "value": 512
                            },
                            "unit": "GiB",
                            "value": 1
                        },
                        "start": {
                            "sector_size": {
                                "unit": "B",
                                "value": 512
                            },
                            "unit": "MiB",
                            "value": 1
                        },
                        "status": "create",
                        "type": "primary"
                    },
                    {
                        "btrfs": [
                            {
                                "mountpoint": "/",
                                "name": "@"
                            },
                            {
                                "mountpoint": "/home",
                                "name": "@home"
                            },
                            {
                                "mountpoint": "/var/log",
                                "name": "@log"
                            },
                            {
                                "mountpoint": "/var/cache/pacman/pkg",
                                "name": "@pkg"
                            }
                        ],
                        "dev_path": null,
                        "flags": [],
                        "fs_type": "btrfs",
                        "mount_options": [
                            "compress=zstd"
                        ],
                        "mountpoint": null,
                        "obj_id": "e973c567-bda4-42a5-a450-e356964b02fc",
                        "size": {
                            "sector_size": {
                                "unit": "B",
                                "value": 512
                            },
                            "unit": "B",
                            "value": null
                        },
                        "start": {
                            "sector_size": {
                                "unit": "B",
                                "value": 512
                            },
                            "unit": "B",
                            "value": 1074790400
                        },
                        "status": "create",
                        "type": "primary"
                    }
                ],
                "wipe": true
            }
        ],
        "disk_encryption": {
            "encryption_type": "lvm_on_luks",
            "iter_time": 1000,
            "lvm_volumes": [],
            "partitions": [
                "e973c567-bda4-42a5-a450-e356964b02fc"
            ]
        },
        "lvm_config": {
            "config_type": "default",
            "vol_groups": [
                {
                    "lvm_pvs": [
                        "e973c567-bda4-42a5-a450-e356964b02fc"
                    ],
                    "name": "ArchinstallVg",
                    "volumes": [
                        {
                            "btrfs": [
                                {
                                    "mountpoint": "/",
                                    "name": "@"
                                },
                                {
                                    "mountpoint": "/home",
                                    "name": "@home"
                                },
                                {
                                    "mountpoint": "/var/log",
                                    "name": "@log"
                                },
                                {
                                    "mountpoint": "/var/cache/pacman/pkg",
                                    "name": "@pkg"
                                }
                            ],
                            "fs_type": "btrfs",
                            "length": {
                                "sector_size": {
                                    "unit": "B",
                                    "value": 512
                                },
                                "unit": "GiB",
                                "value": 50
                            },
                            "mount_options": [
                                "compress=zstd"
                            ],
                            "mountpoint": "/",
                            "name": "root",
                            "obj_id": "5ebc970c-9a79-4206-8236-f8c40150195b",
                            "status": "create"
                        }
                    ]
                }
            ]
        }
    }
}
JSON
