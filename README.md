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

Copies system files and links home configs, replacing existing files.

Edit modules, then regenerate the installation config:

```sh
./generate-config.py
```

Commit modules and `user-configuration.json` together. Modules support native
archinstall settings in `config.json` or commented `config.jsonc`, and `config.sh`
can print generated JSON. `files/home/` supplies individual home links; other
`files/` paths are copied to matching absolute paths.

Requires Python 3; bootstrap also uses archinstall and jq.
Use `./bootstrap.sh --dry-run` to review without installing.
