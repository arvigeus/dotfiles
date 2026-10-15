# Desktop shell implementation

Sources live under [desktop/](symlinks/home/.config/quickshell/desktop/).
Repository provisioning rules are in [the root architecture](../../../ARCHITECTURE.md).

## Lifetimes

`DrawerHost` lazily creates one `DrawerPage`. Closing clears `active` immediately;
the page survives only the exit animation. Bind observation to `active`, and keep
operations that must survive dismissal in feature-local services. Header actions
belong to the page and are loaded by the host; the catalogue must not import services.

## Networking

- `drawers/network/NetworkService.qml` serializes requests to `backend.py` over
  stdin/stdout JSON. The backend uses libnm; passwords never enter argv or status
  snapshots. Mutations survive page dismissal; NetworkManager owns connections.
- Observation runs only while active: status every 5 seconds, scans every 20.
  User actions take priority over queued reads. `Models.js` reconciles keyed rows
  to preserve focus, password input and ordering through refreshes.
- `bar/NetworkStatus.qml` uses native NetworkManager notifications with scanning
  disabled. Keep it independent of the drawer service so bar updates stay cheap.

WARP connects by starting `warp-svc.service`; disconnects and failed connection
attempts stop it. It is never enabled at boot. The polkit rule grants active local
sessions only start/stop access to this unit. Registration is explicit; mode and
registration preferences live in `$XDG_CONFIG_HOME/quickshell/desktop/network.ini`.

`SpeedTestService.qml` runs LibreSpeed separately from network mutations and cancels
on dismissal. CLI JSON speeds are **Mb/s**, latency/jitter are **ms**. Footer rates
come from interface byte counters and use **B/s**. Keep speed-button sizing explicit:
nested layout size hints previously caused a Qt polish loop during drawer opening.

## Validation

```sh
python3 -m unittest discover -s tests -p test_wifi_drawer.py
python3 -m unittest discover -s tests -p test_desktop_interactions.py
```

The tests mock network mutations. Set `WIFI_PREVIEW_PLATFORM=wayland` and
`WIFI_PREVIEW_DIR=/tmp` for native drawer captures; offscreen rendering cannot verify
icon tinting. Treat layout/polish warnings as failures, including during resizing.
