# Desktop credentials

GNOME Keyring provides Secret Service password storage and unlocks automatically
at login, including autologin. KDE applications use their compatibility service
with the same store.

Automatic unlocking uses `~/.config/secret-service/unlock-key`, readable only by
your user. Disk encryption protects this key at rest. The key and encrypted
`~/.local/share/keyrings/` data are backed up together in `dotfiles-private`;
restore both together on a new machine.

```sh
systemctl --user status secret-service-unlock.service
systemctl --user restart gnome-keyring-daemon.service
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for service ordering and credential storage.
