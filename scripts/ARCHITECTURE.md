# Configuration execution

`apply-config.py` parses native settings with archinstall and applies them using
its existing handlers with a small live-system adapter. Its `--dry-run` option
shows the execution scope without running commands. It never constructs a disk
installer or performs installation-only disk, bootloader, or account operations.

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

Home files are published atomically with user ownership. `files/home/` configs and
generated files are copied; `symlinks/home/` configs link to the checkout.
Publishing does not write state manifests or remove omitted outputs.

`repository_policy.py` adapts native repository signature options to require
trusted package signatures while allowing unsigned repository databases. This
fills a gap in archinstall's signature enums; repository URLs remain native.
Both the installation plugin and live adapter use it. `pre.sh` hooks run before
native transactions and again inside the installed target after base
installation, because pacstrap creates a fresh keyring with `-K`.

`config-helpers.sh` provides atomic `file_write` and `file_append` for hooks.

## Private backups

`backup.sh` invokes `private_files.py` against the selected modules' merged
`user-configuration.json`. It does not discover or select modules itself. Each
owning module declares paths using this schema:

```json
{
    "extra": {
        "private": {
            "files": ["home/.ssh", "/etc/example/credentials"],
            "symlinks": ["home/.config/example/token"]
        }
    }
}
```

Both lists contain complete file or directory paths. `home/` is relative to the
invoking user's home; absolute paths target the system. There is no variable or
glob expansion. `files` restores copies; `symlinks` restores links into the
private checkout. The normal public apply/install ignores this metadata.
Backup and restore use the invoking user's permissions; system paths may require
preparing access separately. Hooks can invoke sudo explicitly. Configuration
validation, path conflicts, and unsupported file types fail backup/restore;
`validate.sh` does not validate private declarations.

`--destination PATH` overrides `~/Projects/dotfiles-private`; `--config PATH`
overrides the generated public configuration. `--dry-run` lists planned actions
without copying data or creating a repo. The destination must be outside the
public checkout and cannot be contained in a declared source directory. Backup
materializes source symlinks, rejects cycles and broken links, and skips sockets.
All available sources are staged before any snapshots are replaced. Existing
snapshots are retained for missing sources. Successful refresh replaces complete
directory snapshots, dropping children deleted from the live directory. Omitted
declarations leave old assets on disk but remove them from the restore manifest.
This is a file snapshot, not an application-consistent database backup.

The private repo contains a generated `modules/backup/` with `config.json`,
`files/`, and `symlinks/`. Its manifest saves permissions and directory paths
because Git preserves neither private modes nor empty directories. Payloads and
metadata live only in that repo. The repo root is mode 0700; new control files
are 0600 and `apply.sh` is 0700. Git is initialized locally, without staging,
committing, setting a remote, or uploading. Clone with umask 077 on a new system.

The standalone `apply.py` is a copy of the engine and requires no public checkout
or archinstall. Private `apply.sh` discovers modules directly, merges JSON
objects/lists, installs assets, then runs module `scripts/*.sh` in global filename
order with module path as a tiebreaker. Custom modules live beside the generated
backup module, which backup owns. Handwritten modules follow the public asset
layout and use owner-only modes, retaining executability. There is no private
generator, module selection, dynamic config, or automatic package handling.
Custom configuration is exposed to hooks through a temporary `DOTFILES_CONFIG`
JSON file; they also receive `DOTFILES_REPO`, `USERNAME`, and username as `$1`.
Hooks run from the private checkout as the invoking user with the real home.

Restore checks all destinations and hook syntax before installing. It rejects
overlapping destinations, symlinked payloads, and directory symlinks in target
parents. Existing destinations are renamed to `NAME.before-private-ID` before
replacement. Identical installed links are left in place. There is no global
rollback if a later asset installation or hook fails; prior destinations remain
available beside their replacements. Restore does not remove omitted outputs.
Custom modules, README edits, and Git settings survive subsequent backups.

`python3 -m unittest tests.test_private_files` exercises backup, a local Git
clone, standalone copy/link restore, permissions and empty directories, missing
sources, conflicts, and custom configuration/hooks using temporary fixtures.
