# Architecture

Modules describe the desired system. `generate-config.py` combines the selected
modules into `user-configuration.json`, shared by installation and live apply.
Entry points do not regenerate configuration or select modules.

Prefer native archinstall settings for features it supports. Custom hooks cover
remaining behavior. Package versions are not pinned. Live apply records current
file fingerprints and service ownership to reconcile future changes; it does not
retain configuration migrations or infer ownership of unrelated system files.

## Modules

For theming changes or Union/toolkit upgrades, follow the
[appearance upgrade policy](modules/look-and-feel/ARCHITECTURE.md#union-upgrade-policy):
adopt supported upstream features and retire the adapters they replace.

Modules are discovered under `modules/`. A directory containing configuration,
assets, or hooks is a module; discovery stops there. Configuration fragments are
`config.json`, `config.jsonc` (comments and trailing commas allowed) and
`config.sh`. Other JSON files are assets, not configuration.

Objects merge recursively. Supported native lists and lists under `extra` are
combined; duplicate entries are removed except for `custom_commands`. Conflicting
scalar values fail generation. Native top-level options are checked during
generation; `extra` settings are module-defined.

`modules/hosts/<name>` owns machine identity and installation choices, including
disk layout. `modules/hardware/devices/<name>` owns that machine's hardware
settings and device aliases. Reusable accessories belong under
`modules/hardware/peripherals/`; their matching rules can travel between hosts.

Native archinstall fields control packages and services. Desktop dependencies
are explicit module declarations rather than archinstall's bundled desktop
presets; native application and network handlers still configure their services.
`extra` holds custom metadata, including AUR/Cargo/uv tools, Flatpak
remotes/apps, assets, and hooks. uv tools use `extra.uv_tools` entries with a
tool `name` and install `source`; the package executor updates them from their
declared source and removes tools previously managed by dotfiles when omitted.
`extra.user_services` and `extra.masked_user_services` control global user-unit
enablement/masking; `extra.disabled_services` disables system units. Native
`services`, application and network handlers own enabled system units.
Declare shared script/build tools in their owning modules rather than repeating
them in application modules.

## Selection and hooks

| Source            | Purpose                                                                                         |
| ----------------- | ----------------------------------------------------------------------------------------------- |
| `check.sh`        | Read-only module selection during generation: exit 0 includes, 1 excludes, other statuses fail. |
| `config.sh`       | Emit dynamic JSON configuration during generation.                                              |
| `prerequisite.sh` | Runtime safeguard, run before anything is changed.                                              |
| `pre.sh`          | Early setup before native configuration, including repository key preparation.                  |
| `scripts/*.sh`    | Custom configuration actions, run after assets and extra packages are installed.                 |

Selection checks receive `DOTFILES_HOST`, `DOTFILES_DESKTOP` (default `hyprland`),
and the repository path as their first argument. Select by target-host criteria,
not the generator machine's hardware. Scripts are ordered globally by filename,
then module path for ties; use numeric prefixes for dependencies.

Configuration scripts run from the checkout as root, with the regular user's name
as `$1` and in `USERNAME`, and the checkout in `DOTFILES_REPO`. They read the active
configuration through `/run/system-configuration.json`. Prerequisites and early
hooks run before user/staging-home selection; they receive the selected live user
as `$1`, or an empty argument on the ISO, and must operate on the system directly.
Generation records which hooks exist, so editing a hook needs no regeneration;
adding or removing one does.

Keep fixed configuration in assets. Use scripts for generated content and runtime
actions. Avoid explicit service restarts; users reboot after applying changes.

## Assets

`files/` assets are copied; `symlinks/` assets link to the checkout. Within either
directory, `home/` targets the regular user's home and other paths target `/`.
Keep application-rewritten configuration in `files/home/` to avoid checkout noise.
Use plain installed filenames such as `bash.sh` or `fcitx.conf`.
Generation checks explicit and discovered assets together: sources must be files
inside the checkout, destinations must be normalized paths, and no destination
may be duplicated or used as another asset's parent directory.

Hooks write generated home configuration into a temporary staging home (`HOME`
and the XDG variables point there). Home outputs are published with user
ownership; generated outputs are regular files. `file_write`/`file_append` also
stage system outputs through `DOTFILES_SYSTEM_STAGE`; direct download hooks use
the same staging prefix. Publication compares content/mode/link fingerprints
against the last applied state, preserves local changes for review, and removes
clean outputs whose owning declaration disappeared. Arbitrary runtime hook
actions remain imperative; they cannot be rolled back as a filesystem transaction.

## Shell environment

Declare environment variables once, in `files/etc/environment.d/*.conf`. The
systemd user manager reads them, and `/etc/profile.d/environment.sh` exports the
same result to login shells; graphical sessions inherit it from the login shell.
Aliases and other interactive Bash settings go in `files/etc/bash.bashrc.d/*.sh`,
which `/etc/bash.bashrc` sources. The managed `~/.bashrc` is empty so the
system-wide settings take effect. Cache files use `~/.local/cache`; the Codex
desktop runtime installer still creates `~/.cache/codex-runtimes`. Codex,
Cargo, Go, Pi, and Copilot CLI use `~/.local/share/{codex,cargo,go,pi,copilot}`.
Go's build cache and npm use XDG cache paths; npm config uses XDG config. Claude
Code stores its config under `~/.config/claude`; its separate `~/.claude.json`
remains at home. GnuPG keeps its standard private `~/.gnupg` home. Code - OSS extensions use
`$XDG_DATA_HOME/vscode-oss/extensions`, and shared state uses
`$XDG_STATE_HOME/vscode-oss/shared-data`; the project launchers pass those
paths to Code - OSS. Its product-specific `~/.vscode-oss/argv.json` remains at
home.

## Boot and login

EFI stub boot uses UKIs. A final boot hook quiets archinstall's kernel command
line, drops the stock splash image and rebuilds the UKIs. Routine boot output is
suppressed; errors and the disk-unlock prompt remain visible.

## Mirrors

The mirrorlist module runs Reflector on the Arch ISO before installation, using
its declared HTTPS, freshness, and download-speed policy. Pacstrap copies the
selected list into the target. The installed `reflector.timer` refreshes it;
live apply preserves the list rather than restoring fixed mirror URLs.

## Execution

`bootstrap.sh` runs prerequisites and early setup on the ISO, then invokes
archinstall. The installation plugin copies the checkout into the target and
runs early setup again after base installation, before application packages.
Archinstall's single custom command then runs `scripts/configure.sh`.

`apply.sh` validates the configuration, then uses a live adapter around
archinstall's parser and native handlers. The adapter first collects packages,
services and generated native files in a temporary root. It applies packages,
network, profile, console, and zram settings, followed by the same custom command. Installation-only
disk, bootloader, account, and snapshot operations are skipped. System locale is
configured at installation; live apply leaves it unchanged. Login services are
enabled without restarting the session.

See [scripts/ARCHITECTURE.md](scripts/ARCHITECTURE.md) for executor, adapter and
helper details.

## Development checks

`lint.sh` inspects tracked and unignored, untracked files. Its default mode is
read-only; `--fix` formats files before running the same checks. It formats
Python with Ruff, shell scripts with shfmt, QML with qmlformat, and JSON with
Python's JSON encoder. It checks Python with Ruff, shell syntax and lint with
Bash and ShellCheck, QML parsing through the Qt 6 qmlformat, JSON syntax, and
JSONC module fragments through the parser used by `generate-config.py`. Required
commands are checked only when their file type is present. `ruff.toml` pins the
lint rules and format style; tests ignore E402 because they add module paths
before importing.
ShellCheck runs in Bash mode because many managed shell fragments are sourced
files and do not have shebangs; SC1091 is ignored for an asset sourced from the
runtime XDG configuration path.
