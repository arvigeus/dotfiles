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
