# Configuration execution

`apply-config.py` parses native settings with archinstall and applies them using
its existing handlers with a small live-system adapter. Its `--dry-run` option
inspects installed packages and managed file differences without running hooks,
package transactions, or service changes. It never constructs a disk
installer or performs installation-only disk, bootloader, or account operations.
Live custom commands receive `DOTFILES_REPO` so their script paths remain rooted
in the checkout while `/run/system-configuration.json` points to a frozen
configuration snapshot.

`copy-checkout.py` is an archinstall plugin. Its `on_install` hook copies the
checkout into `/root/system-configuration` inside the target and runs early setup
there. Archinstall then executes `custom_commands`, whose first entry runs
`configure.sh`. The copy skips bytecode and local tool/cache directories.

`configure.sh` is the custom-configuration executor. `--check` and `--pre` run only
those hooks. A full run installs declared assets, runs `extra-packages.sh`,
executes `scripts/*.sh` hooks in the generated order and publishes the staged
home with `publish-home.py`. During installation it first copies the checkout to
`~/Projects/dotfiles` and continues from there, so symlinked assets point into
the user's checkout. Everything runs in one archinstall custom command, because
each command gets a fresh `arch-chroot -S` `/tmp`.

AUR modules should declare concrete package targets when a package name has
multiple providers, so noninteractive apply does not prompt for a provider.

AUR installation uses Paru as the regular user. If Paru is missing or cannot run,
the executor builds the source `paru` package with `makepkg`, linking it against
the installed pacman libraries. This permits reinstalling the same version after
a libalpm change. AUR package installation retains `--needed`. A temporary
`package-build` sudoers rule permits pacman during builds and is removed when the
package installation exits. `--aur` keeps declared AUR targets from being
replaced by differently named repository providers. Paru's source build follows its
[upstream installation instructions](https://github.com/Morganamilo/paru#installation).

`extra.cargo_packages` is a merged list of crates.io binary crate names. The
package installer runs `cargo install --locked -- CRATE` for each as the regular
user, with `CARGO_HOME=~/.local/share/cargo`; it never installs into the staging
home or compiles as root. Cargo skips installed current versions without forced
rebuilds. Its toolchain must be declared by the owning language module. The
system Cargo environment adds that directory's `bin` to the desktop PATH.

`extra.uv_tools` is a list of `{name, source}` records. The installer runs
`uv tool install --upgrade --from SOURCE NAME` as the regular user. It records
managed names under `~/.local/state/dotfiles/uv-tools` and uninstalls only those
names when their declarations disappear; unrelated uv tools remain untouched.
An individual uv install, update or uninstall failure is reported as a warning
and does not stop the remaining apply steps. Failed updates retain the prior
managed record; failed removals stay recorded so a later apply retries them.
Failed first-time installs are not recorded as managed. The `uv` executable
belongs to the Python language module. Topgrade's `uv` step updates installed
tools and managed Python installations. A failed `uv` step follows Topgrade's
normal retry/continue/quit handling. Configuration apply reconciles declared
tools from their configured sources.

Home files are published atomically with user ownership. `files/home/` configs and
generated files are copied; `symlinks/home/` configs link to the checkout.
Publication and service ownership share the reconciliation state described below.

`repository_policy.py` adapts native repository signature options to require
trusted package signatures while allowing unsigned repository databases. This
fills a gap in archinstall's signature enums; repository URLs remain native.
Both the installation plugin and live adapter use it. `pre.sh` hooks run before
native transactions and again inside the installed target after base
installation, because pacstrap creates a fresh keyring with `-K`.

`config-helpers.sh` provides atomic `file_write DEST [COMMAND ARG…]` and
`file_append` with the same arguments. A producer's failure discards its temporary
output and preserves the destination. Use stdin only for literal here-documents;
piping a producer into the helper hides its exit status until after publication.

## Reconciliation

Live apply holds an exclusive lock and freezes the generated JSON for the run.
Preflight checks all asset sources, destinations and hook syntax before setup.
Native archinstall handlers collect into a temporary root: their files use the
same publication rules as assets and hook outputs. Pacman configuration is merged
with the existing file, preserving unrelated settings; prior managed custom
repository sections are replaced or removed. Reflector retains dynamic mirror
ownership. Package transactions remain full `pacman -Syu --needed` upgrades.

`reconcile.py` stores one current manifest at `/var/lib/dotfiles/UID/state.json`.
Each ownership scope records SHA-256/mode for files or the exact symlink target.
Missing files are installed; identical files retain their modification time.
If a destination still matches its applied fingerprint, a changed source replaces
it even when Git checkout timestamps are older. Differing untracked files and
locally changed destinations require individual diff/replace/keep review. A kept
conflict retains its prior ownership record and returns status 2, rather than
claiming convergence. Initial installation can replace package/user defaults;
the first live apply adopts matching files and reviews other existing files.
For a text diff, `apply.sh` opens Meld as the invoking user when a graphical
session and Meld are available. It compares temporary copies, with the invoking
user's home and XDG directories so staged setup paths do not leak into the GUI;
otherwise review prints the existing unified diff. `apply.sh` forwards graphical
session and XDG values under private variable names; reconciliation supplies them
only to Meld.

Omitted tracked files are removed only when clean or explicitly approved. Empty
directories and untracked files are not swept. Each replaced/removed entry is
backed up under `backups/RUN/absolute/path` inside the state directory, with no
automatic pruning. State and backups are private; publication is atomic per file
and checkpoints after each successful operation. Failed/interrupted runs can be
retried: matching content is adopted even if its state checkpoint was interrupted.
There is no whole-system rollback for pacman, boot rebuilding or arbitrary hooks.

`reconcile_packages.py` reads libalpm through PyALPM, resolving virtual providers
and the transitive dependencies of declared native/AUR packages. The running
kernel is protected too. Base, storage/boot tools and the AUR helper are explicit
package declarations. Extra explicit packages and true orphans are review
candidates; installed dependencies are never mistaken for extra applications.
Each approved removal is a separate non-recursive `pacman -R`, retaining native
dependency checks and `.pacsave` handling. Inventory is reread before each
choice. Kept packages are offered again until declared or removed; no hidden
exception list is saved. Without a terminal, removals are skipped.
Flatpak/Cargo installations still use their native commands; their removal is
outside the pacman/AUR review.

Only tracked service enablement/masks are removed when declarations disappear.
Unrelated units are untouched. Enabled system services are started without
restarting active units; disabling a unit does not stop a live session. Global
user-unit changes settle at the next login. Reboot remains the activation boundary
for session and boot changes.

Dry-run can preview declared assets/native files and package/service intent;
generated hook outputs are known only after hooks run. In tests,
`DOTFILES_STATE_DIR` selects a disposable state directory and `DOTFILES_CONFIG`
selects the frozen JSON. These variables are passed to the executor, not stored in
module configuration.
