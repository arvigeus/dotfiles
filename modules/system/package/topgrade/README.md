# Updates

Run `system-update`, or use **Update system** in the System drawer. Topgrade updates
supported installed tools and shows Arch news through paru/yay. Afterwards it
offers to remove selected orphan packages, review configuration with Meld, and
restart selected services using replaced files. Run `package-maintenance` to
repeat this review independently. Login/session services are left for logout or
reboot.

Claude Code and Pi update through the system package manager; their plugins and
extensions update separately through Topgrade.

When the private `system-agent` is installed, updates capture their output and
package versions, then offer an investigation after maintenance. Its project and
instructions live in `~/Projects/dotfiles-private/projects/system-agent/`.
Without it, updates run ordinary Topgrade. Running `topgrade` directly still
provides version snapshots and the optional review, with limited console context.

Pacnew review uses Meld. `pacnew-review` also runs it independently, using
sudoedit for protected files. Without a terminal or graphical session, it only
lists unresolved files. The default scan follows installed package backup entries;
`pacnew-review --find` also searches `/etc` for files left by removed packages.

Package caches remain available for rollback; use the Disks drawer for cleanup.
Personal Topgrade settings can override the defaults in
`~/.config/topgrade.d/maintenance.toml`.

See [implementation notes](ARCHITECTURE.md).
