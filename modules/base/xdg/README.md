# Desktop defaults

XDG cache files live in `~/.local/cache`; config, data, and state use the usual
`~/.config`, `~/.local/share`, and `~/.local/state` defaults. Both shell startup
and the systemd user environment receive these declarations.

Standard home folders, including Projects, are created during setup so Dolphin
can populate its Places sidebar on first launch.

Default applications are configured in `files/etc/xdg/mimeapps.list`: Dolphin,
Firefox, Kate, Koko, Okular, LibreOffice, fooyin, mpv, Thunderbird, qBittorrent
and Ark.
User-selected associations take precedence.

See [implementation notes](ARCHITECTURE.md).
