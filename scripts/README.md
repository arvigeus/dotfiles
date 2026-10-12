# Configuration execution

`apply-config.py` parses native settings with archinstall and applies them using
its existing handlers with a small live-system adapter. Its `--dry-run` option
shows the execution scope without running commands. It never constructs a disk
installer or performs installation-only disk, bootloader, or account operations.

`copy-checkout.py` is an archinstall plugin. Its `on_install` hook copies the
checkout into `/root/system-configuration` inside the target. Archinstall then
executes the declared `custom_commands`, starting the generated executor. The
plugin excludes the session scratchpad and local tool/cache directories.

`templates/user-configuration.sh` supplies the executor template.
`templates/extra-packages.sh` and `publish-home.py` are embedded in the generated
`user-configuration.sh`; they are not separate runtime entry points. Module hook
bodies and the helpers they use are snapshotted into ordered `custom_commands`. Changing
a module script or helper requires regeneration before apply uses the change.

AUR installation uses Paru as the regular user. If Paru is missing or cannot run,
the executor builds the source `paru` package with `makepkg`, linking it against
the installed pacman libraries. This permits reinstalling the same version after
a libalpm change. AUR package installation retains `--needed`.

The temporary `package-build` sudoers rule permits pacman during builds and is
removed when the package-installation subprocess exits. Paru's source build
follows its [upstream installation instructions](https://github.com/Morganamilo/paru#installation).

Home files are staged and published atomically with user ownership. `files/home/` configs
and generated files are copied; `symlinks/home/` configs link to the checkout. Publishing does not
write state manifests or remove omitted outputs.
Staging uses `/var/tmp` because archinstall runs each custom command in a separate
`arch-chroot -S` invocation with a fresh `/tmp`.


`repository_policy.py` adapts native repository signature options to require
trusted package signatures while allowing unsigned repository databases. This
fills a gap in archinstall's signature enums; repository URLs remain native.
Both the installation plugin and live adapter use it. `pre.sh` hook bodies are
snapshotted in `extra.pre` and run before native transactions and inside the
installed target after base installation, because pacstrap creates a fresh
keyring with `-K`.
