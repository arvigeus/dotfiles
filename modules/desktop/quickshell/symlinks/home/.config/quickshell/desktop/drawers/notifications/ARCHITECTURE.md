# Native notifications

`NotificationCenter` is an engine singleton started first by `shell.qml`, so
another service's startup error cannot keep activation callers waiting, and
independently of the lazy drawer. A `Quickshell.Services.Notifications.NotificationServer` owns
`org.freedesktop.Notifications`. No second notification daemon or history polling
is used. `desktop/notifications` owns libnotify and the per-user D-Bus activation
entry, which shadows other installed entries for the name (such as Plasma's).
Activation only starts `desktop-shell.service` (`SystemdService=`, `Exec=/bin/false`):
a bus without systemd activation fails rather than launching a shell outside the
unit. The graphical session normally starts the unit already.

`NotificationCard` serves popups and history using the live palette. Images must
resolve locally or through Quickshell's provider; absent images reserve no space.
Bodies are plain text: strip notification/Pango tags and decode entities without
removing literal generic syntax such as `Vec<String>`. Markup, inline replies and
remote images are not advertised. Actions invoke native NotificationAction objects;
never reconstruct commands or restore dead callbacks from history.

At most three popup cards appear on the output focused when they arrive, with a
fallback if that output disappears. Layer surfaces take no keyboard focus and
reserve no desktop space. Long popup stacks scroll within the available output
height. Popups animate in, pause their deadline while hovered
(a window removed with its output releases the pause),
and use the client's timeout or six seconds by default. A zero timeout or default
critical urgency remains visible until hidden. Hiding a normal popup retains its
notification and actions in the drawer; it does not acknowledge or close the app's
notification. Transient notifications never enter history and expire when hidden.
Do Not Disturb sends new low and normal notifications directly to history without
replaying them when quiet mode ends; critical ones still pop up, and enabling quiet
mode leaves visible critical popups in place. Popups are also suppressed while the Notifications drawer
is open; general computer activity is never a suppression signal.

Each saved record has a persisted `seen` flag and retains the notification's
`desktopEntry` for tray sender matching, falling back to the app name. Tray primary activation
acknowledges only that sender's records through the ordinary `markSeen` path.
New and replacement notifications arriving outside the drawer start unseen.
The bar bell uses `unseenCount` for its
highlight, count and tooltip. Opening the drawer acknowledges all saved items;
notifications received while it stays open are already seen. Invoking an action
or explicitly hiding a popup acknowledges that item. A timeout or quiet delivery
does not imply the user read it. Transient notifications do not enter the count.
Reload preserves seen state; records lacking the field load as seen. Client
closure preserves the latest acknowledged state rather than an older snapshot.

`qs ipc -c desktop call notifications status` reports only quiet mode, whether
the drawer is open, and history/popup/unseen counts, without notification content.

Replacements update the existing ID and popup in place, preserving its hover
state, rather than duplicating history or rebuilding the visible card.
The drawer's `KeyedModel` keeps card objects by ID.
The server retains tracked notifications through Quickshell configuration reloads;
re-emitted notifications restore their live actions and history position without
showing a second popup. History and quiet state are loaded before the server
starts accepting notifications. Up to 100 ordinary notifications are retained;
evicted live records expire. Clients withdrawing a notification remove its saved card too.

`NotificationCenter` persists history and quiet state with a `FileView`
(`atomicWrites`, `blockLoading`) at
`$XDG_STATE_HOME/quickshell/desktop/notifications.json`, defaulting to
`~/.local/state/quickshell/desktop/notifications.json`. The file is read once,
synchronously, before the server starts, and written within 150 ms of a change;
a stream of updates cannot postpone the write.
Loading and saving both normalize: at most 100 records, bounded plain-text fields,
remote icon URLs dropped, and no actions or images (they belong to the live D-Bus
connection). The shell service's `UMask=0077` makes new files private; an existing
file keeps its mode.
Records are keyed internally and keep the server ID with `Quickshell.instanceId`,
which survives reloads but not restarts. A re-emitted notification reclaims only
its own record, even after a restart reuses the PID and server IDs restart. Saved
history remains readable across shell restarts, but only current live connections
have actions. Errors never log notification content.

Protocol/API references: [desktop notifications](https://specifications.freedesktop.org/notification-spec/latest/),
[NotificationServer](https://quickshell.org/docs/v0.3.2/types/Quickshell.Services.Notifications/NotificationServer/).
