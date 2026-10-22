# Early boot

The boot module uses a directly booted UKI. Archinstall owns the initramfs hooks
and disk-unlock parameters; the module does not replace them or convert between
BusyBox and systemd early userspace.

The setup hook adjusts console verbosity while preserving root and encryption
parameters. It validates UKI presets before replacing the command line, then
rebuilds the images using the existing mkinitcpio configuration. Explicit preset
configuration files remain supported; no mkinitcpio hook override is shipped.

Archinstall enables mkinitcpio's stock `--splash` option embedding the Arch logo
in the UKI. The setup hook clears an options assignment containing only that
stock image, leaving the firmware's BGRT graphics visible until console takeover.
Custom splash images and options remain untouched. Plymouth is not required for
this brief UEFI stage; a Plymouth theme would instead provide graphics during
Linux startup and disk unlock.

With systemd in the initramfs, `systemd-analyze time` reports initrd separately
from kernel time; password-entry time remains part of initrd time. Use the raw
kernel timestamps from `dmesg` when comparing hardware initialization between
boots, since journal import can timestamp buffered messages later.
The graphical target's critical chain is not necessarily the autologin path:
inspect `getty@tty1.service` and user session units too.

Before changing a live UKI, retain a separate copy of the working image and a
firmware entry pointing to it. Boot configuration can be validated and image
contents inspected without a restart, but startup performance and successful
disk unlock require a subsequent boot to verify.

References: [mkinitcpio configuration](https://man.archlinux.org/man/mkinitcpio.conf.5),
[cryptsetup generator](https://www.freedesktop.org/software/systemd/man/latest/systemd-cryptsetup-generator.html).
