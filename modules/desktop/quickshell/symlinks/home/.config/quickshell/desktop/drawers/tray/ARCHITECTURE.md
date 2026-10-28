# System tray

`TrayService` derives the bar badge and attention list from Quickshell's
`SystemTray` and `NotificationCenter`; `TrayDrawer` is the lazy drawer page. Host
registration and native actions are summarized in the
[module architecture](../../../../../../../ARCHITECTURE.md#system-tray-and-bar-badges).

## Names and notification matching

An item's name is its Title, else its tooltip title, else its ID. Electron
publishes `chrome_status_icon_N` with an empty Title, so its tooltip title is the
only app name it exposes.

An unseen notification belongs to an item when the sender's desktop entry or app
name equals the item's ID or name, compared trimmed, case-insensitively and
without a `.desktop` suffix. A reverse-DNS ID (three or more segments) also
answers to its last segment, but only against a full name on the other side:
`com.rtosta.zapzap` matches an item `zapzap`, while `org.a.Client` and
`com.b.Client` stay distinct. Substrings never match. Only records whose `seen`
is `false` count. Primary activation of a non-menu-only item acknowledges the
matched records; secondary activation, scrolling and menus do not, and an
app-owned `NeedsAttention` status remains until the app clears it.

## Drawer lifecycle

The list binds `SystemTray.items` directly, so registrations and removals insert
or remove rows; other rows keep their focus, hover and menu anchor. Rows are focus
scopes: syncing `currentIndex` from a focused control would otherwise move focus
to the row itself and trap Tab in the first row.

One `QsMenuAnchor` shows the selected item's DBusMenu. It is closed before its
target changes, because Quickshell 0.3.2 keeps an open anchor open, with its old
menu referenced, when `menu` is reassigned. It also closes on dismissal, when its
item unregisters (before Quickshell deletes the item) and when the item drops its
menu. Escape cancels a menu that is still loading over D-Bus.

## Verification

`tests/test_tray_drawer.py` runs every QML case on a private bus
(`support.private_bus`), where `SystemTray` becomes the watcher and never
registers with the user's session. Fake items sit in a `ScriptModel` standing in
for `SystemTray.items`. `tests/fixtures/tray_service.py` publishes a real SNI item
and DBusMenu; the native case covers menu semantics, activation, scrolling,
status, removal and a same-ID replacement while a menu is open. Menus run
offscreen, because synthetic input has no seat serial for a grabbing popup. Icon
themes are checked only with `DISPLAY_PREVIEW_PLATFORM=wayland`, which opens a
real window. Pointer grabs and real applications need a desktop session.
