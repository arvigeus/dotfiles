# Shared provider accounts

`nextcloud.py` owns the Nextcloud account, its app password and the authenticated
DAV transport. Consumers import it from the desktop root; feature configuration
never holds account URLs or passwords. Runtime files live outside the checkout in
`$XDG_CONFIG_HOME/quickshell/desktop/integrations/`:

- `nextcloud.json`: `{"url": …, "username": …}`. `url` is the HTTPS instance root,
  including any installation subdirectory. Other keys are ignored.
- `nextcloud-app-password`: one line holding a Nextcloud app password.

Create both with private permissions, for example:

```sh
install -Dm600 /dev/stdin ~/.config/quickshell/desktop/integrations/nextcloud.json <<'EOF'
{"url": "https://cloud.example.com/", "username": "alice"}
EOF
install -Dm600 /dev/stdin ~/.config/quickshell/desktop/integrations/nextcloud-app-password
```

The second command reads the app password from standard input; end it with
Ctrl+D. Runtime reads require a current-user-owned regular file with mode 0600,
refuse symlinks, and reject empty or multiline secrets. Do not put real
credentials in managed module assets.

`DAVClient` accepts an explicit consumer scope. Authenticated requests and redirects
must remain within that path on the configured HTTPS origin, without traversal,
URL credentials, queries or fragments. CalDAV scopes to the current user's calendar
home. Responses are bounded to 16 MiB. Error messages exclude response bodies and
secrets. Each request has an 18-second network timeout. The password stays in
Python, never in QML, process arguments, snapshots or logs.

The calendar backend reads its collection selections from `calendar.json`
separately; feature configuration cannot override account identity or the password.

References: [Nextcloud app passwords](https://docs.nextcloud.com/server/latest/user_manual/en/session_management.html)
and [CalDAV](https://docs.nextcloud.com/server/latest/user_manual/en/groupware/sync_kde.html).
