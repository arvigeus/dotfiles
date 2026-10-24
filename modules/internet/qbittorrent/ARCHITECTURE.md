# qBittorrent

The module installs Arch's native `qbittorrent` package. The hook merges the
live user's Qt INI file into the staging home, retaining unrelated settings and
Qt-serialized values. It refuses to run while that user's client is running,
since qBittorrent would overwrite changes on exit. Publishing preserves user
ownership and mode 0600. qBittorrent owns subsequent saves and can reset the
file mode to 0644 when rewriting it.

Settings follow qBittorrent 5.3's layout: Web UI settings live in `[WebUI]`;
`Search\SearchEnabled` remains in `[Preferences]`. The Web UI listens on IPv4
loopback port 8080, with localhost authentication bypass for local integrations.
HTTPS and UPnP port mapping are disabled; CSRF and Host-header checks remain on,
with localhost as the allowed domain (the listener's IP is accepted natively).
The GUI client requires stored credentials even with localhost auth bypass.
The merger retains an existing username/hash; otherwise it sets `admin` and a
PBKDF2-SHA512 hash of a discarded random password (16-byte salt, 100,000 rounds).
Nothing needs to know that password for local access. No firewall opening or background
daemon is needed. The Movies space can launch the desktop client on demand.

Plugin sources and their refresh schedule belong to the private module. This
public module neither downloads plugins nor installs a pacman hook.

`python3 -m unittest tests.test_qbittorrent` checks preservation of existing Qt
configuration, replacement of managed settings, fresh setup, and repeat apply.
