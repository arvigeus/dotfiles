# Cloudflare WARP

`warp-svc.service` is installed disabled and never starts at boot. Consumers start
it on connect and stop it on disconnect; the Quickshell network drawer does this
through `systemctl --no-ask-password`.

`files/etc/polkit-1/rules.d/50-desktop-warp.rules` lets active local `wheel`
sessions start and stop only that unit without an authentication prompt. Other
units, verbs and unit-file changes keep their default policy.
