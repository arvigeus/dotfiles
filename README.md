# Dotfiles

On an official Arch Linux ISO, connect to the internet, clone this repo, then
run as root:

```sh
./bootstrap.sh
```

Enter the username when prompted and create that same account in archinstall.
Review the settings before installing: the saved layout wipes `/dev/nvme0n1`
and uses sizes specific to the original disk. Configuration targets archinstall 4.5.

Installation copies this checkout to `$HOME/Projects/dotfiles` and applies it.
Keep credentials and private files out of the repo.

On your running system, apply changes as your regular user:

```sh
./apply.sh
```

Updates additional packages, copies system files, enables additional services, and links home configs.

`host` selects `modules/hosts/zephyrus` or `modules/hosts/vm`. Modules are discovered
automatically; an optional module `hosts` file limits it to the listed host names.
`./bootstrap.sh` defaults to Zephyrus; `./bootstrap.sh vm` prompts for the VM disk
and capacity. All hosts share the storage layout and require UEFI; choose VM
graphics in archinstall. Installation remembers the selected host and disk settings.

Edit modules, then regenerate the installation config:

```sh
./generate-config.py
```

Commit modules and `user-configuration.json` together. Modules support native
archinstall settings in `*.json` or commented `*.jsonc`, and `config.sh`
can print generated JSON (`--configure` requests fresh settings during bootstrap).
`files/home/` supplies individual home links; other
`files/` paths are copied to matching absolute paths.

Requires Python 3 and jq; bootstrap also uses archinstall.
Use `./bootstrap.sh --dry-run` to review without installing.
