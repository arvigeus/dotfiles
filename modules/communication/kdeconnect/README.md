# KDE Connect

Pair a phone with the computer to share files and clipboard contents, control
media, and use remote input. Install KDE Connect on the phone and connect both
devices to the same Wi-Fi.

```sh
kdeconnect-cli --refresh
kdeconnect-cli --list-devices
kdeconnect-cli --device <id> --pair
kdeconnect-cli --list-available
```

On iPhone, allow Local Network access and keep KDE Connect on screen; iOS cannot
keep the connection alive with the app in the background. If discovery fails,
use the phone app's device-by-IP option with the computer's Wi-Fi address.

The module allows pairing and discovery through the firewall on private and
link-local networks. See [firewall architecture](../../system/security/firewall/ARCHITECTURE.md).
