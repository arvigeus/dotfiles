# Dotfiles

Modular configuration for installing Arch Linux with archinstall and applying
configuration to an existing system. The aim is to keep this repository as the
source of truth for the live system as well as the initial installation.

This is a personal setup. Review the selected host and its settings before using
it. Requires Python 3, jq, and archinstall 4.5. Package versions are not pinned.

## Configure

Edit the configuration and assets in [modules/](modules/). The [host](host) file
selects the default machine; pass a host name to generate for another target.

```sh
./generate-config.py       # Default host
./generate-config.py vm    # VM configuration
```

Use `./generate-config.py --configure` to prompt for dynamic module settings
again. Review and commit both generated files: `user-configuration.json` and
`user-configuration.sh`. Regenerate after changing modules or shared helpers;
installation and live apply consume the generated files directly.

## Install

From a checkout on the Arch ISO, run as root:

```sh
./bootstrap.sh
```

Review the disk layout first: **the Zephyrus configuration wipes `/dev/nvme0n1`**.
Create one regular user in archinstall. The checkout is installed at
`~/Projects/dotfiles` for that user.

Supply account credentials and the disk encryption password interactively or
with archinstall's `--creds` file, passed to `bootstrap.sh`. Without an encryption
password, archinstall does not load the declared encryption settings; a dry-run
alone cannot confirm them.

## Test in a VM

Run `./vm.sh` and enter an Arch ISO path. Requires `qemu-desktop`, `qemu-img`,
`edk2-ovmf`, `libarchive`, Python 3, and access to `/dev/kvm`. The ISO mounts
this checkout automatically and prints the VM configuration and installation
commands. Use `./vm.sh boot` to boot the installed disk without an ISO.

The writable share also changes the host checkout. A persistent 64 GiB disk and
UEFI settings live under `${XDG_STATE_HOME:-~/.local/state}/dotfiles-vm`.

## Apply to a live system

Run as your regular user:

```sh
./validate.sh
./apply.sh
```

Validation runs archinstall's silent, offline dry-run. It does not execute custom
commands or validate `extra`.

Apply updates packages and settings and runs the generated hooks. It skips disk,
bootloader, account creation, and filesystem snapshot initialization. Reboot
after applying to activate changed settings.

Managed configuration is replaced on each apply. Omitted files, packages, and
services are left in place; removal and migration are manual. There is no
backward compatibility support: update your system when the configuration changes.

Hyprland starts automatically on TTY1. Spaces offers **Go to gaming mode**;
Steam's **Go to Desktop** or **Exit Steam** returns to Hyprland. Gaming mode is
temporary: rebooting starts the desktop. **Restart → Reload** closes applications
and immediately starts a fresh desktop session. Gaming startup failures return
to the desktop automatically.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the module conventions and execution
model, and [execution-tool details](scripts/ARCHITECTURE.md) for the scripts.
