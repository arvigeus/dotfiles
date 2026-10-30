# Desktop credentials

GNOME Keyring provides Secret Service password storage. KDE applications access
it through their standard compatibility service.

With an empty keyring password, autologin needs no unlock prompt. The keyring is
then unencrypted and relies on disk encryption and user-only file permissions.
With a nonempty password, unlock it when first needed each session.

A nonempty keyring password
must be remembered when restoring on another machine.

```sh
systemctl --user status gnome-keyring-daemon.service
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for configuration ownership.
