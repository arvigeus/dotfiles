# Architecture

Modules describe the desired system. Generation combines them into
`user-configuration.json` and `user-configuration.sh`, shared by installation and
live apply. Entry points do not regenerate configuration or select modules.

Prefer native archinstall settings for features it supports. Custom hooks cover
remaining behavior. The configuration does not pin package versions, track
previous system state, or automatically remove declarations that disappear.
Breaking changes require manual migration; compatibility layers are not maintained.

## Modules

Modules are discovered under `modules/`. A directory containing configuration,
assets, or hooks is a module; discovery stops there. Configuration fragments use
`config.json`, `config.jsonc`, `config.sh`, `NAME.config.json`, or
`NAME.config.jsonc`. JSONC accepts comments and trailing commas. Other JSON files
are assets, not configuration fragments.

Objects merge recursively. Supported native lists and lists under `extra` are
combined; duplicate entries are removed except for `custom_commands`. Conflicting
scalar values fail generation. Native top-level options are checked during
generation; `extra` has no custom schema validator.

`modules/hosts/<name>` owns machine identity and installation choices, including
disk layout. `modules/hardware/devices/<name>` owns that machine's hardware
settings and device aliases. Reusable accessories belong under
`modules/hardware/peripherals/`; their matching rules can travel between hosts.

Native archinstall fields control packages and services. `extra` holds custom
metadata, including AUR packages, Flatpak remotes/apps, assets, and hooks.
`extra.packages`, `extra.services`, `extra.disabled_services`, and
`extra.masked_services` are descriptive lists, not execution instructions.
Declare shared script/build tools in their owning modules rather than repeating
them in application modules.

## Selection and hooks

| Source            | Purpose                                                                                         |
| ----------------- | ----------------------------------------------------------------------------------------------- |
| `check.sh`        | Read-only module selection during generation: exit 0 includes, 1 excludes, other statuses fail. |
| `config.sh`       | Emit dynamic JSON configuration during generation.                                              |
| `prerequisite.sh` | Runtime safeguard, snapshotted into the generated configuration.                                |
| `pre.sh`          | Early setup before native configuration, including repository key preparation.                  |
| `scripts/*.sh`    | Custom configuration actions, snapshotted with shared helpers into `custom_commands`.           |

Selection checks receive `DOTFILES_HOST`, `DOTFILES_DESKTOP` (default `hyprland`),
and the repository path as their first argument. Select by target-host criteria,
not the generator machine's hardware. Scripts are ordered globally by filename,
then module path for ties; use numeric prefixes for dependencies.

Keep fixed configuration in assets. Use scripts for generated content and runtime
actions. Avoid explicit service restarts; users reboot after applying changes.

## Assets

`files/` assets are copied; `symlinks/` assets link to the checkout. Within either
directory, `home/` targets the regular user's home and other paths target `/`.
Keep application-rewritten configuration in `files/home/` to avoid checkout noise.
Use plain installed filenames such as `bash.sh` or `fcitx.conf`.

The XDG module declares directories in both shell startup and the systemd user
environment. Cache files use `~/.local/cache`; other XDG directories use their
standard defaults.

Scripts write generated home configuration into a temporary staging home.
Home outputs are published with user ownership; generated outputs are regular
files. Publishing replaces managed destinations and leaves omitted outputs alone.

## Boot and login

EFI stub boot uses UKIs. A final boot hook adapts archinstall’s encryption
command line for the declared systemd initramfs and rebuilds the UKIs. Routine
boot output is suppressed; errors and the disk-unlock prompt remain visible.

## Mirrors

The mirrorlist module runs Reflector on the Arch ISO before installation, using
its declared HTTPS, freshness, and download-speed policy. Pacstrap copies the
selected list into the target. The installed `reflector.timer` refreshes it;
live apply preserves the list rather than restoring fixed mirror URLs.

## Execution

`bootstrap.sh` runs prerequisites and early setup on the ISO, then invokes
archinstall. The installation plugin copies the checkout into the target and
runs early setup again after base installation, before application packages.
Archinstall runs the generated custom commands to finish configuration.

`apply.sh` validates the configuration, then uses a live adapter around
archinstall's parser and native handlers. It applies packages, network, profile,
console, and zram settings, followed by the same custom commands. Installation-only
disk, bootloader, account, and snapshot operations are skipped. System locale is
configured at installation; live apply leaves it unchanged. Login services are
enabled without restarting the session.

The generated executor installs declared assets and extra packages and coordinates
hook execution and home publication. Hooks read the active configuration through
`/run/system-configuration.json`. Each custom command runs in a separate shell;
exports do not carry between commands. Shared staging and temporary invocation
context bridge those commands and are cleaned up after completion or on the next
invocation following an interruption. They are not system-state manifests.

See [scripts/ARCHITECTURE.md](scripts/ARCHITECTURE.md) for executor, adapter and
shared-helper details.
