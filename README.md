# Dotfiles

From an official Arch Linux ISO, connect to the internet, clone this repository,
and run as root:

```sh
./bootstrap.sh
```

This generates `user-configuration.json` and opens archinstall with those settings.
Review them in the installer before starting. The saved storage layout wipes
`/dev/nvme0n1` and contains sizes specific to the original disk.
Set users and passwords in archinstall; credentials are not stored here.
Bootstrap prompts for the account to configure. Create that same account in
archinstall.

Bootstrap adds a chroot command to a temporary installation config carrying the
current checkout, including Git history and uncommitted files (excluding
`.agents`, `.aws`, and `.codex`). It copies this to `$HOME/Projects/dotfiles`,
sets ownership, and runs `link-home.sh`. Keep private files out of this checkout.
An existing destination checkout is rejected.

Each regular file under module `files/home/` is symlinked to its corresponding
home path; directories remain ordinary directories. Add files to the module and
rerun `link-home.sh` to manage them. New files created by apps remain local.
Each destination belongs to one module.
To apply them on a running system, run as your regular user:

```sh
./link-home.sh
```

Existing files are moved to `~/.local/state/dotfiles/backup.*` before linking.

Edit the modules, then regenerate without running the installer:

```sh
./generate-config.py
```

Requires Python 3 (included with archinstall). Commit modules and the generated
file together to track the resulting changes.

Modules are grouped by purpose, for example `modules/desktop/hyprland`,
`modules/hardware/amd`, and `modules/hardware/storage`.
Every module containing `config.json`, `config.jsonc`, or `config.sh` is included automatically
in sorted path order:

- `config.json` contributes native archinstall settings. Nested objects merge;
  repeated values are rejected. Package, service, and
  `app_config.fonts_config.fonts` lists merge with duplicates removed, keeping
  first occurrence order. `custom_commands` appends in order, retaining repeats.
- `config.jsonc` uses the same keys and supports `//` and `/* ... */` comments
  outside strings. Trailing commas are not supported.
- Optional `config.sh` runs in its module directory with Bash strict mode and
  prints a JSON object to stdout. Keep it limited to generating configuration;
  send diagnostics to stderr. If multiple config files exist, all contribute.
- Plain files and other scripts can live beside the configuration. The generator
  does not use them yet.

Hyprland contributes its profile and ly greeter; AMD contributes
`profile_config.gfx_driver`. Fonts live in `modules/look-and-feel/fonts`;
other modules can contribute fonts using the same native setting.
Module metadata never enters the generated archinstall JSON.

Installer arguments are forwarded, for example `./bootstrap.sh --dry-run`.
The saved configuration is from archinstall 4.5; review compatibility with the
version on your ISO. See the [archinstall CLI documentation](https://man.archlinux.org/man/archinstall.1.en).

Module `custom_commands` run after repository copying and home linking.
Generation checks JSON and merge conflicts; validation against the installed
archinstall version is still to be added.
