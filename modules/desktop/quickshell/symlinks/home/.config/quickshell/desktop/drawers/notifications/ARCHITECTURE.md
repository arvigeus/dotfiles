# Native notifications

`NotificationCenter` is an engine singleton started by `shell.qml`, independently
of the lazy drawer. A `Quickshell.Services.Notifications.NotificationServer` owns
`org.freedesktop.Notifications`. No second notification daemon or history polling
is used. `desktop/notifications` owns libnotify, the D-Bus activation entry and
the cleanup hook removing Dunst supplied by Archinstall. D-Bus activation starts
`desktop-shell.service` (`SystemdService=`); the graphical session normally starts
it already.

`NotificationCard` is shared by popup and history. It consumes the live shell
palette, fonts and radii; no copied theme file needs regeneration. Cards display
app icons, plain text, optional images, urgency, progress and actual app-provided
actions. Urgency uses a noninteractive header icon with a tooltip and accessible
label: down arrow for low, info for normal, alert triangle for critical. Only
critical urgency uses the danger color; card borders stay neutral and there is
no decorative urgency stripe. Images resolve only from local paths or Quickshell's image provider;
remote image URLs are ignored. Named theme images are resolved and checked as
small header icons, not promoted to artwork; missing icons fall back to the Lucide
bell without requesting the image provider's checkerboard placeholder. Attachment
space appears only for a successfully decoded image. Common action identifiers
and clear folder/playback/download labels receive optional Lucide icons alongside
their text; ambiguous actions remain text-only. Markup, hyperlinks, protocol action
icons and inline replies
are not advertised. App actions are invoked through NotificationAction, never
reconstructed as commands. Closing an action makes its saved card inert; history
never invents a launch target or restores a stale callback.

At most three popup cards appear on the output focused when they arrive, with a
fallback if that output disappears. Layer surfaces take no keyboard focus and
reserve no desktop space. Long popup stacks scroll within the available output
height. Popups animate in, pause their deadline while hovered,
and use the client's timeout or six seconds by default. A zero timeout or default
critical urgency remains visible until hidden. Hiding a normal popup retains its
notification and actions in the drawer; it does not acknowledge or close the app's
notification. Transient notifications never enter history and expire when hidden.
Do Not Disturb sends new notifications directly to history without replaying them
when quiet mode ends. Popups are also suppressed while the Notifications drawer
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

The drawer has no explanatory banners or Show again action.
Its trash icon clears immediately; per-card X dismisses that item. Errors use a
fixed-height line so storage status cannot move controls or cards.

Replacements update the existing ID and popup in place, preserving its hover
state, rather than duplicating history or rebuilding the visible card.
The drawer reconciles its ListModel by ID, preserving unchanged card objects.
The server retains tracked notifications through Quickshell configuration reloads;
re-emitted notifications restore their live actions without showing a second
popup. History and quiet state are loaded before the server starts accepting
notifications. Up to 100 ordinary notifications are retained; evicted live records
expire. Clients withdrawing a notification remove its saved card too.

`NotificationCenter` persists history and quiet state with a `FileView`
(`atomicWrites`, `blockLoading`) at
`$XDG_STATE_HOME/quickshell/desktop/notifications.json`, defaulting to
`~/.local/state/quickshell/desktop/notifications.json`. The file is read once,
synchronously, before the server starts, and written 150 ms after the last change.
Loading and saving both normalize: at most 100 records, bounded plain-text fields,
remote icon URLs dropped, and no actions or images (they belong to the live D-Bus
connection). The shell service's `UMask=0077` makes new files private; an existing
file keeps its mode.
Notification IDs are scoped by an internal key; saved records from a
prior process cannot invoke a new process's unrelated notification. Saved history
remains readable across shell restarts, but only current live connections have
actions. Errors never log notification content.

Verification uses `tests/test_notification_history.py`: fixtures use temporary
state roots; native receipt/action tests run under `dbus-run-session`
and never send notifications to the user's session. Desktop interaction and
configuration-generation fixtures cover drawer hosting and package ownership.
Protocol/API references: [desktop notifications](https://specifications.freedesktop.org/notification-spec/latest/),
[NotificationServer](https://quickshell.org/docs/v0.3.2/types/Quickshell.Services.Notifications/NotificationServer/).
