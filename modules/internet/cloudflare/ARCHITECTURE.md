# Cloudflare WARP

`warp-svc.service` is installed disabled and never starts at boot. Consumers start
it on connect and stop it on disconnect; the Quickshell network drawer does this
through `systemctl --no-ask-password`.

The drawer waits for daemon IPC readiness, queries registration and creates one
only for the CLI's `MissingRegistration` result. Existing registrations are reused;
other errors never trigger replacement or deletion. Connecting accepts Cloudflare's
terms. Mode selection persists independently of the stopped daemon. Disconnect
always attempts to stop the service, even if the CLI is unavailable or times out;
failed connection setup also stops it. Error messages identify the failed stage
without forwarding CLI diagnostics or registration credentials.
Status/settings reads also pass `--accept-tos`: the CLI rejects noninteractive
reads without it, even after connecting with that flag.

`files/etc/polkit-1/rules.d/50-desktop-warp.rules` lets active local `wheel`
sessions start and stop only that unit without an authentication prompt. Other
units, verbs and unit-file changes keep their default policy.
