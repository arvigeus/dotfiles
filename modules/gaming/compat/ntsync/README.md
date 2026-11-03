# NTSync

Loads the kernel's NTSync driver at boot for compatible Wine and Proton runners.
Select a runner with NTSync support in your game launcher; GE-Proton 10-10 and
newer enable it automatically when available.

After applying, reboot or run `sudo modprobe ntsync` to activate it immediately.
Restart existing Wine sessions before launching games. Check device access with
`test -r /dev/ntsync && test -w /dev/ntsync`; while a game is running,
`sudo fuser -v /dev/ntsync` shows processes using it.

See [ARCHITECTURE.md](ARCHITECTURE.md) for configuration details.
