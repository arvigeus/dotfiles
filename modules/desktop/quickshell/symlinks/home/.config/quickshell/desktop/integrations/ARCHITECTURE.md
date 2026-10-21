# Shared provider accounts

`nextcloud.py` owns the account, named credentials and authenticated DAV transport.
Consumers import it from the desktop root; they must never keep account URLs or
passwords in their feature configuration. Runtime configuration lives outside the
checkout in `$XDG_CONFIG_HOME/quickshell/desktop/integrations/nextcloud.json`.

The account schema contains `url` (HTTPS instance root, including any installation
subdirectory), `username`, `credentials` and `capabilities`. Each named credential
is `{ "provider": "file", "file": "dav-app-password" }`. Each capability references
one credential: `{ "credential": "dav" }`. `credential(account, capability="dav")`
is the consumer boundary. CalDAV and future WebDAV share `dav`; a future Music
consumer can select `music_subsonic` with a distinct Music API key. Declaring a
capability does not implement its API. This separation permits independent
provider modules, such as Google, without treating Nextcloud as a calendar account
or forcing unrelated credentials into a single universal token.

Credential files resolve under `integrations/credentials/nextcloud/`. Runtime reads
require a current-user-owned regular file with mode 0600, refuse final symlinks and
paths escaping that directory, and reject empty or multiline secrets. The importer
accepts older source file modes and writes private destination files atomically;
it validates every destination before writing, refuses conflicting contents and
never removes sources. It can resume an interrupted import. Configuration files
are also written as 0600. Do not put real credentials in managed module assets.

`DAVClient` accepts an explicit consumer scope. Authenticated requests and redirects
must remain within that path on the configured HTTPS origin, without traversal,
URL credentials, queries or fragments. CalDAV scopes to the current user's calendar
home; future WebDAV consumers must choose their own scope. Responses are bounded
to 16 MiB. Error messages exclude response bodies and secrets. Each request has an
18-second network timeout. Credentials remain in Python, never in QML, process
arguments, snapshots or logs.

The calendar backend's provider boundary reads `calendar.json` separately. Only
`calendars` and `task_lists` selections are passed through; feature configuration
cannot override account identity or credentials. `provider` currently supports
`nextcloud`. Future calendar providers can dispatch here without moving their
accounts into a drawer. No Files, Music or Gmail functionality is implemented by
this module.

References: [Nextcloud app passwords](https://docs.nextcloud.com/server/latest/user_manual/en/session_management.html)
and [CalDAV](https://docs.nextcloud.com/server/latest/user_manual/en/groupware/sync_kde.html).
