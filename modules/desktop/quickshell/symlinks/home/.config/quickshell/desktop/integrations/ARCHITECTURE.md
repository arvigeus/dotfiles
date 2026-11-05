# Shared provider accounts

Runtime files live outside the checkout in
`$XDG_CONFIG_HOME/quickshell/desktop/integrations/`. `private.py` locates that
directory and reads credential files: only regular files of at most 64 KiB, opened
non-blocking (a FIFO cannot stall a worker) and checked through the opened
descriptor. Credentials require owner-only access by the current user, for
example mode 0600.
Callers choose whether a symlink is accepted; when it is, the link target is
checked. Movies and TV Series read their per-Space `media.json` through the same
reader (see [Movies](../spaces/movies/ARCHITECTURE.md#private-configuration-and-provisioning)).
Do not put real credentials in public module assets.

## Nextcloud

`nextcloud.py` owns the Nextcloud account, its app password and the authenticated
DAV transport. Consumers import it from the desktop root; feature configuration
never holds account URLs or passwords. Files:

- `nextcloud.json`: `{"url": …, "username": …}`. `url` is the HTTPS instance root,
  including any installation subdirectory. Other keys are ignored.
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
Ctrl+D. Both secrets must be owner-only regular files, not symlinks, holding one
nonempty line.

`DAVClient` accepts an explicit consumer scope: a collection path ending in `/`,
because `allowed()` is a prefix test. Authenticated requests, redirects and
`Destination` headers (COPY/MOVE) must remain within that path on the configured
HTTPS origin, without traversal, URL credentials, queries or fragments. CalDAV
scopes to the current user's calendar home. Responses are bounded to 16 MiB.
Error messages exclude response bodies and secrets; HTTP 412 raises
`PreconditionFailed`, so callers can tell a refused `If-Match`/`If-None-Match`
guard from other failures. Each request has an 18-second network timeout. The
password stays in Python, never in QML, process arguments, snapshots or logs.

The calendar backend reads its collection selections from `calendar.json`
separately; feature configuration cannot override account identity or the password.

`subsonic.py` owns the shared Music transport. Radio's station adapter and
Music's library/stream clients use `load_account()` and `music_api_key()` from
this integration. No per-Space credential copy is used.
The client scopes requests to `index.php/apps/music/subsonic/rest/` beneath the
HTTPS instance root, sends credentials only in POST form bodies, rejects redirects
and redacts provider errors. Refused redirects and oversized replies keep their own
messages; malformed HTTP is reported as an unreadable response. See
[Radio sync](../spaces/radio/ARCHITECTURE.md) and
[Music library/streaming](../spaces/music/ARCHITECTURE.md).

References: [Nextcloud app passwords](https://docs.nextcloud.com/server/latest/user_manual/en/session_management.html)
and [CalDAV](https://docs.nextcloud.com/server/latest/user_manual/en/groupware/sync_kde.html).

## qBittorrent

Movies, TV Series, Games and Books read one connection configuration from
`torrents.json`. There are no per-Space copies or compatibility fallbacks. Each
Space still owns its torrent worker, jobs, import records, tags and library database.

The shared backend remains in `spaces/movies/torrent_backend.py`. Its
`QUICKSHELL_MEDIA_SPACE` environment selects data and job identity, never account
configuration. The JSON keys are `url`, optional `username`/`password`, and
optional `api_key`; see [the secret-free example](torrents.example.json).
`torrents.json` may be a symlink. A file holding a `password` or `api_key` must
be owner-only; a credential-free connection file has no mode requirement. Keys
remain in Python and are not exposed to QML.

Requests never follow redirects: urllib would copy the `Authorization` header to
any redirect target. Set `url` to the final Web UI origin. A non-HTTP listener on
that origin reports the Web UI as unreachable.

The managed loopback client needs only `{"url":"http://127.0.0.1:8080"}`.
The qBittorrent module enables localhost authentication bypass. Leave credentials
empty for that connection: a nonempty `api_key` selects Bearer authentication,
so a stale key fails even with localhost bypass. Remote clients need credentials
valid for that server and matching local download mounts.

## Gemini

`gemini-api-key` belongs to [Streaming](../spaces/streaming/ARCHITECTURE.md). It
uses the same reader, may be a symlink, and must hold one owner-only line.
