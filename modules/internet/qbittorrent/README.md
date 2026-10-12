# qBittorrent

[Upstream](https://www.qbittorrent.org/)

For a stuck Flatpak instance, close qBittorrent before removing its lockfiles:

```bash
rm ~/.var/app/org.qbittorrent.qBittorrent/config/qBittorrent/ipc-socket \
   ~/.var/app/org.qbittorrent.qBittorrent/config/qBittorrent/lockfile
```
