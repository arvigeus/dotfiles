# Pacman maintenance hooks

This module owns pacman-contrib (including pacdiff and paccache) and
archlinux-contrib (checkservices). The mirrorlist module owns only mirror policy,
Reflector and pkgstats. Hooks are copied into `/etc/pacman.d/hooks` by normal
asset publication; adding them to the manifest does not install them on the host.

`99-report-orphans.hook` runs after install, upgrade or removal transactions.
`pacman-report-orphans` queries `pacman -Qtdq` with a ten-second deadline. Exit 1
with no output is the normal empty result; stderr, contradictory output or other
statuses are errors. It only prints candidates and review/keep instructions.
Queries are allowed while the transaction lock remains held; no second package
transaction is started.

`99-report-stale-services.hook` runs after upgrades. Its helper skips systems
without a running systemd manager and chroots, including archinstall's target.
It runs `timeout 30s checkservices -F -P -L -R`: uppercase flags disable failed
unit output, pacdiff, daemon reload/reexec and service restarts. These defaults
must be disabled explicitly because bare checkservices is interactive and can
change services. Failed or timed-out checks remain visible as hook errors.
Systemd's existing package-provided daemon reload/restart hooks remain in charge
of their own units; this hook only reports other candidates.

These are PostTransaction reports, with no AbortOnFail, network access, desktop
session lookup or unattended cleanup. Pacman retains its own upgrade exit and
hook diagnostics. Topgrade supplies updates/news and an interactive post-update
review for orphan removal, Meld configuration review and service restarts; see
[the workflow](../topgrade/ARCHITECTURE.md). Those actions run after the transaction
lock is released and re-read candidates. The
Disks drawer owns cache deletion, Reflector owns mirror updates, mkinitcpio's
native hooks rebuild UKIs and System's info popup reports missing running-kernel
modules. No duplicate automatic implementation is added for these tasks.

References: [arch-update tasks](https://github.com/Antiz96/arch-update),
[checkservices flags and behavior](https://github.com/archlinux/contrib/blob/master/admin/checkservices),
[ALPM hook format](https://man.archlinux.org/man/alpm-hooks.5.en).

Run `python3 -m unittest discover -s tests -p test_package_maintenance.py`.
Tests use isolated commands; they never mutate packages or host services.
