# Desktop Secret Service

The module installs GNOME Keyring and libsecret and enables the packaged
`gnome-keyring-daemon.service` and its socket. It uses the package's normal
startup, prompting, and credential storage.

The setup hook writes `[KSecretD] Enabled=false` in the staged `kwalletrc`,
leaves the KWallet API enabled, and disables automatic legacy-wallet migration.
KDE's `kwalletd6` compatibility service forwards calls to
`org.freedesktop.secrets`, provided by GNOME Keyring. KWallet's own storage
backend is not used.

Autologin supplies no password to unlock an encrypted store. A nonempty keyring
password therefore requires an unlock prompt when first needed each session.
An empty password keeps the standard keyring usable without prompts and stores
its contents unencrypted; the encrypted filesystem and file permissions provide
protection at rest. Applications own their authentication dialogs and saved entries.
There are no custom startup overrides, unlock keys, credential importers, or
PAM changes.

Credential storage lives in `~/.local/share/keyrings`. Stop credential
consumers and the daemon before restoring keyring files, then start the daemon
again. The user supplies the keyring password; it is not stored in dotfiles.

Validate module discovery using `python3 -m unittest tests.test_generation`.

References: [GNOME Keyring](https://help.gnome.org/seahorse/keyring.html)
and [KWallet Secret Service support](https://github.com/KDE/kwallet/blob/v6.31.0/README.md).
