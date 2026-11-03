# NTSync

This shared compatibility module declares Arch's
[`ntsync-autoload`](https://archlinux.org/packages/extra/any/ntsync-autoload/)
package for both hosts. It owns `/usr/lib/modules-load.d/10-ntsync.conf`, so
systemd loads the kernel module at boot. The selected Arch kernels provide the
`NTSYNC-MODULE` dependency. No DKMS build, initramfs change, custom udev rule or
configuration hook is needed.

The [kernel driver](https://docs.kernel.org/userspace-api/ntsync.html) provides
`/dev/ntsync`; runner support determines whether a Wine session uses it.
[GE-Proton 10-10](https://github.com/GloriousEggroll/proton-ge-custom/releases/tag/GE-Proton10-10)
enables NTSync automatically. No global Wine synchronization variables are set,
so other runners retain their own fallback behavior. The configured Bottles,
Heroic and Lutris Flatpaks already allow device access.
