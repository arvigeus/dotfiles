# qBittorrent

The module installs Arch's native `qbittorrent` package. The hook merges the
live user's Qt INI file into the staging home, retaining unrelated settings and
Qt-serialized values. It refuses to run while that user's client is running,
since qBittorrent would overwrite changes on exit. Publishing preserves user
ownership and mode 0600. qBittorrent owns subsequent saves and can reset the
file mode to 0644 when rewriting it.

`python3 -m unittest tests.test_qbittorrent` checks preservation of existing Qt
configuration, replacement of managed settings, fresh setup, and repeat apply.
