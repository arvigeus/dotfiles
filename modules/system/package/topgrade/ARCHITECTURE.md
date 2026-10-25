# Update integration

The System drawer launches the ordinary `topgrade` command through its existing
terminal helper. It adds no flags, alternate updater or root wrapper. The
Topgrade module already declares the AUR package; it must be installed before
using the button. User-owned main configuration retains Topgrade's normal
precedence over the managed `topgrade.d/maintenance.toml` fragment.

The fragment enables Arch news (`show_arch_news`), leaves package-manager
selection to Topgrade and disables cleanup. Topgrade updates native/AUR packages,
Flatpaks and supported development tools. Disks remains the explicit cache-cleanup
entry point; package caches can also supply pacdiff merge bases.

Claude Code and Pi executables are managed by pacman/AUR. Disable their built-in
steps because they invoke executable self-updates. Claude's package launcher
sets `DISABLE_UPDATES=1`; Pi's step otherwise invokes `pi update --self` before
updating extensions. Keep `claude_code_plugins` enabled and update Pi extensions
with a custom `pi update --extensions` command, guarded for installations without
Pi. The separate qBittorrent search-plugin command remains enabled.

Topgrade 17.14.1 already skips packaged Bun, Deno, Codex and Zed self-updates by
installation path. OpenCode skips executable updates outside its script-install
directory while retaining plugin updates. uv handles externally managed builds
and still updates its tools/Python installations; mise checks `mise doctor` for
self-update availability (false for the installed Arch build). pip3 respects
Python's externally managed marker. Keep these steps and npm/pnpm/Cargo/plugin
updates enabled rather than disabling everything whose launcher belongs to
pacman. Topgrade's installed build has no self-update feature enabled.

Topgrade's built-in `config_update` launches pacdiff as root and preserves
DIFFPROG, but does not use pacdiff's sudoedit mode. This fragment disables that
step and replaces it with one post-command, `package-maintenance`. That command
runs orphan review, the Meld module's `pacnew-review`, then service review in a
fixed order. There is no second root GUI editor or duplicate pacnew merge step.
Topgrade's native distribution summary still lists pacnew/pacsave files.

`pacnew-review` refuses root execution, explicitly exports `DIFFPROG=meld` and
runs `pacdiff --sudo --backup --cachedir <archive-view>`. Pacdiff invokes sudoedit
with Meld as SUDO_EDITOR
for viewing/editing protected files; copying/removal remains in pacdiff's normal
interactive workflow. No --newtab flag is supplied: the editor must wait for its
own comparison to close before sudoedit copies changes back. Automatic diff3
merge is distinct from the graphical editor and retains its native behavior.
Without interactive stdin or DISPLAY/WAYLAND_DISPLAY, the helper runs only
`pacdiff --output`. Arguments remain separate and can select pacdiff's native
find/three-way options. The default package-database scan excludes files left
behind by uninstalled packages; the distribution summary and optional --find
scan can reveal those files, subject to the user's directory access.

Pacdiff 1.13.1 recursively scans its cache even for a two-way View. Pacman's
private `download-*` directories are intentionally inaccessible to the regular
user and would produce permission warnings. The wrapper builds a temporary
symlink view of readable top-level `*.pkg.tar*` archive files from each
`pacman-conf CacheDir`, excluding signatures and directories. Earlier configured
caches win duplicate archive filenames. Passing this view to pacdiff retains old
merge bases without scanning partial-download directories. An EXIT trap removes
the view on success or failure; package archives, cache permissions and diagnostic
stderr are unchanged.

`package-maintenance` runs only as the regular user. Its numbered selectors accept
individual entries, all entries or an empty selection to skip. Orphan candidates
come from a bounded `pacman -Qtdq` query with validated names. After selection it
queries again, drops packages no longer orphaned and invokes
`sudo -- pacman -Rns -- <selected>` with native package confirmation still enabled.
A failed query never becomes an empty healthy result or a removal target list.

Service candidates come from `sudo -- /usr/local/libexec/pacman-report-services`,
the same bounded read-only helper used by the hook. Only full-line quoted service
names are accepted from its C-locale output; diagnostics stop the review rather
than supplying targets. Display managers, getty/user-manager instances, logind,
D-Bus and auditd are excluded in addition to checkservices' default exclusions.
Chosen units are handled individually with `sudo -- systemctl try-restart --
<unit>`, so a service stopped after inspection is not started. One restart failure
does not prevent attempts for other selected units, but retains an overall failure
status. No reload/reexec or automatic-confirmation flags are added.

Meld configuration review runs before services are offered; a failure in that
step skips service review. Orphan-review failures are reported but do not prevent
configuration review. EOF skips a selection; Ctrl+C cancels the remaining workflow.
Without interactive stdin, only the existing orphan reporter and pacnew file
listing run, with no sudo invocation or service restart scan. This interactive
workflow is outside pacman's transaction lock; the ALPM hooks remain report-only.

[Pacman reports](../pacman/ARCHITECTURE.md) cover orphan packages and stale
services for updates made with any pacman frontend. Their findings are re-read
at interactive review time rather than stored as an actionable snapshot. Existing
mirror, cache and boot-image mechanisms are not duplicated.

References: [Topgrade configuration](https://github.com/topgrade-rs/topgrade/blob/main/config.example.toml),
[Arch updater](https://github.com/topgrade-rs/topgrade/blob/main/src/steps/os/archlinux.rs),
[config_update](https://github.com/topgrade-rs/topgrade/blob/main/src/steps/os/linux.rs),
[pacdiff modes](https://man.archlinux.org/man/pacdiff.8.en).

Verification uses `tests/test_package_maintenance.py`, `tests/test_system_drawer.py`
and the generation suite. No test runs Topgrade against the host's package state.
