# Shared provider accounts

## Nextcloud

`nextcloud.py` owns the Nextcloud account, its app password and the authenticated
DAV transport. Consumers import it from the desktop root; feature configuration
never holds account URLs or passwords. Runtime files live outside the checkout in
`$XDG_CONFIG_HOME/quickshell/desktop/integrations/`:

- `nextcloud.json`: `{"url": …, "username": …}`. `url` is the HTTPS instance root,
  including any installation subdirectory. Other keys are ignored by this
  transport. Dolphin's private setup additionally records `http_auth_realm` here
  from the server's authentication challenge for unattended KDE authentication.
- `nextcloud-app-password`: one line holding a Nextcloud app password.
- `nextcloud-music-api-key`: one line holding the API key generated in Nextcloud
  Music settings for Subsonic access. Music uses this key rather than the DAV app
  password, with the same account URL and username.

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

`subsonic.py` owns the shared Music transport. Radio's station adapter and
Music's library/stream clients use `load_account()` and `music_api_key()` from
this integration. The Music key uses the same ownership, 0600 and no-symlink rules
as the DAV secret. It is declared once in the quickshell module's `extra.private`
and restored alongside the existing account/password through `backup.sh` and the
private checkout's standalone apply. No per-Space credential copy is used.
The client scopes requests to `index.php/apps/music/subsonic/rest/` beneath the
HTTPS instance root, sends credentials only in POST form bodies, rejects redirects
and redacts provider errors. See [Radio sync](../spaces/radio/ARCHITECTURE.md) and
[Music library/streaming](../spaces/music/ARCHITECTURE.md).

References: [Nextcloud app passwords](https://docs.nextcloud.com/server/latest/user_manual/en/session_management.html)
and [CalDAV](https://docs.nextcloud.com/server/latest/user_manual/en/groupware/sync_kde.html).

## qBittorrent

Movies, TV Series and Games read one connection configuration from
`$XDG_CONFIG_HOME/quickshell/desktop/integrations/torrents.json`. The quickshell
module owns its single `extra.private.files` declaration. `backup.sh` stores
one matching file under the private repository's generated `modules/backup`;
standalone private restore recreates it with 0600 permissions and private parents.
There are no per-Space copies or compatibility fallbacks. Each Space still owns
its torrent worker, jobs, import records, tags and library database.

The shared backend remains in `spaces/movies/torrent_backend.py`. Its
`QUICKSHELL_MEDIA_SPACE` environment selects data and job identity, never account
configuration. The JSON keys are `url`, optional `username`/`password`, and
optional `api_key`; see [the secret-free example](torrents.example.json).
Keys remain in Python and are not exposed to QML.

The managed loopback client needs only `{"url":"http://127.0.0.1:8080"}`.
The qBittorrent module enables localhost authentication bypass. Leave credentials
empty for that connection: a nonempty `api_key` selects Bearer authentication,
so a stale key fails even with localhost bypass. Remote clients need credentials
valid for that server and matching local download mounts.
