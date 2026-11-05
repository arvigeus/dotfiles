# Games

Open **Spaces → Games** for Steam/Epic/GOG libraries, IGDB discovery, favorites,
ProtonDB ratings, title artwork, playtime and HowLongToBeat estimates.
Installed Steam games and public store descriptions work without API keys.

**Filters → NSFW** in the header shows adult games while highlighted; it starts
off and remembers your choice. It hides games that GOG tags NSFW or that Steam
rates for adult or frequent sexual content. Steam games known to your Steam client
are classified offline from its cache; other Steam titles share one request per
100 games. GOG uses one weekly listing of every NSFW-tagged product; it omits
GOG's unlisted ("secret") products, such as Agony, so those stay visible. A new
title stays hidden only until its first lookup. Games without a store label (Epic, local files, or a store that is
unreachable) stay visible. Hover the toggle for counts; Refresh retries
unreachable stores.

The ProtonDB badge shows **Native** when Steam offers a Linux build.

Configure `~/.config/quickshell/desktop/spaces/games/games.json` using
[games.example.json](games.example.json). A Twitch application's
`igdb_client_id` and `igdb_client_secret` enable Browse. Optional `steam_api_key`
and 17-digit `steam_id` enable ownership checks for a public Steam profile.
Sign into Epic with `legendary auth`; the Legendary module supplies its launcher
and UMU. Steam and Legendary accounts require sign-in after a fresh installation.
Epic purchases appear after **Refresh**; Games re-reads Epic ownership every few
hours and keeps the saved list while Epic is unreachable. After an uninstall, the
store button updates once the launcher finishes. Epic installations show progress
on the store button and speed/ETA below it;
**Downloads** lists tracked installs. Downloads continue when Games closes, and
reopening restores their progress. Click Install again to retry a failed download.

For GOG, enable the `gaming/launchers/heroic` module, sign into GOG in Heroic and
refresh its library, then refresh Games. Native and Flatpak Heroic are supported;
Heroic supplies GOGdl, so no additional Python library or GOG API key is needed.
Install opens Heroic's confirmation; play uses its existing Wine/Proton settings
and cloud-save support. Use **Manage in Heroic** for updates and uninstalling.
Refresh Heroic first when purchases or installations change; Games reads its
cached library and does not sign into GOG itself.

Steam's custom title/hero artwork takes priority. When HowLongToBeat has no match,
click its clock to enter a game link or ID. Estimates
and descriptions stay available offline after their first successful lookup.

**Find** uses qBittorrent search and imports completed game files into **Local**.
Configure the shared `~/.config/quickshell/desktop/integrations/torrents.json` using the
[connection example](../../integrations/torrents.example.json); the managed local client
only needs `{"url":"http://127.0.0.1:8080"}`; keep the file mode 0600 if you add a
password or API key. Imported archives/installers open in
the file manager; they are never automatically executed.

Game files, Wine prefixes,
saves, Heroic settings and custom Steam artwork need their own backup. See
[architecture](ARCHITECTURE.md) for storage, provider and lifecycle details.
