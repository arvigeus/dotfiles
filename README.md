# Dotfiles

Modular configuration for installing Arch Linux with archinstall and applying
configuration to an existing system. The aim is to keep this repository as the
source of truth for the live system as well as the initial installation.

This is a personal setup. Review the selected host and its settings before using
it. Requires Python 3, jq, and archinstall 4.5; apply's package preview uses
PyALPM (`pyalpm`). Package versions are not pinned.

## Configure

Edit the configuration and assets in [modules/](modules/). The [host](host) file
selects the default machine; pass a host name to generate for another target.

```sh
./generate-config.py       # Default host
./generate-config.py vm    # VM configuration
```

Use `./generate-config.py --configure` to prompt for dynamic module settings
again. Review and commit the generated `user-configuration.json`. Regenerate after
changing module configuration or adding, removing or selecting modules, assets or
hooks; edits to existing assets and hooks apply directly.

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

## Development checks

Run `./lint.sh` to check source formatting and syntax, or `./lint.sh --fix` to
format supported files first. See [development checks](ARCHITECTURE.md#development-checks)
for the covered file types and tools.

## Apply to a live system

Run as your regular user:

```sh
./validate.sh
./apply.sh --dry-run
./apply.sh
```

Validation runs archinstall's silent, offline dry-run. It does not execute custom
commands or validate `extra`.

Apply installs missing packages, updates the system, reconciles managed files and
services, and runs the module hooks. It skips disk,
bootloader, account creation, and filesystem snapshot initialization. Reboot
after applying to activate changed settings.

Copied files use content comparisons, not timestamps. Clean managed files update
automatically; local edits and differing files on the first apply get individual
diff/replace/keep review. Skipped file conflicts return exit status 2. Replaced and
removed files are backed up under `/var/lib/dotfiles/UID/backups/`.

Extra pacman/AUR packages are offered one at a time, with declared dependencies protected.
Keep anything you still need and add it to its module. Use
`./apply.sh --no-package-review` to skip package removals. Non-interactive runs
keep conflicting files and skip removals.

Files and service enablement previously managed by apply are reconciled when
removed from the configuration. Untracked files and unrelated services are left
alone. See [reconciliation details](scripts/ARCHITECTURE.md#reconciliation).

Hyprland starts automatically on TTY1; see the [desktop README](modules/desktop/hyprland/README.md)
for the session, gaming mode and shortcuts.

## Private backups

Declare private paths under `extra.private` in their module's `config.json`, then
regenerate configuration. Run as your regular user with Python 3 and Git:

```sh
./backup.sh --dry-run
./backup.sh
```

This creates or updates `~/Projects/dotfiles-private`, including a standalone
`apply.sh` for a new system. It supports copies, symlinks, and custom private
modules with installation hooks. Review and commit the private repo yourself.
Close applications that write backed-up files first; missing paths retain their
previous backup. See the [private configuration conventions](scripts/ARCHITECTURE.md#private-backups).

See [ARCHITECTURE.md](ARCHITECTURE.md) for the module conventions and execution
model, and [execution-tool details](scripts/ARCHITECTURE.md) for the scripts.
