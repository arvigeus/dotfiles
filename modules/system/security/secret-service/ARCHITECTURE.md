# Desktop Secret Service

The module installs GNOME Keyring and enables its packaged user daemon/socket.
A service drop-in launches the daemon through the unlock helper with Type=dbus,
so consumers wait until org.freedesktop.secrets is actually owned.
`secret-service-unlock.service` is wanted by and ordered after that daemon,
before `graphical-session-pre.target`. Its `PartOf` relationship reruns unlocking
when the daemon is restarted. Consumers that require unattended credential access
must order themselves after and require this unlock service.

`secret-service-unlock` creates a random 384-bit URL-safe unlock key on first use
and passes it through an anonymous stdin pipe when starting
`gnome-keyring-daemon --foreground --unlock`. The helper execs the daemon,
retaining the systemd main PID. GNOME applies --unlock at daemon startup; it is
not used to launch a second daemon against an already-running store. It never passes
the key in arguments, environment variables or logs. The key file must be a
current-user-owned regular file with mode 0600; symlinks are refused. Its parent
and the keyrings directory use mode 0700. The helper refuses to generate a new
key when an existing persistent keyring is present. A missing or mismatched key
fails without an interactive unlock prompt or password reset.

The daemon creates an encrypted login keyring. The helper checks that this
collection is unlocked and establishes its default alias only when none exists;
it refuses to replace a different default collection. There are no PAM edits or
login-password dependencies. The existing LUKS-encrypted filesystem and user
permissions are the security boundary for unattended unlocking.

The setup hook selects third-party Secret Service storage with
`kwalletrc`'s `[KSecretD] Enabled=false`, leaves the KWallet API enabled, and
disables automatic legacy-wallet migration. KDE's `kwalletd6` compatibility
process forwards calls to `org.freedesktop.secrets`; `ksecretd` is not used.
The public module contains no credentials. Its `extra.private` declarations
capture the unlock key and encrypted keyrings together; restore while credential
consumers are closed, then restart the daemon so it reads the restored store.

Validation uses a private D-Bus session and isolated HOME/XDG directories to
exercise real keyring creation, noninteractive unlock after a daemon restart,
persistent secret recovery, and refusal to replace a keyring whose key is missing.
Native KIO authentication is checked separately against the private Nextcloud
account without permitting authentication dialogs or logging filenames/passwords.

References: [GNOME Keyring daemon](https://github.com/GNOME/gnome-keyring/blob/main/daemon/gnome-keyring-daemon.service.in)
and [KWallet Secret Service support](https://github.com/KDE/kwallet/blob/v6.31.0/README.md).
