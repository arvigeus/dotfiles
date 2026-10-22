# Calendar and task drawers

`EventsDrawer.qml` presents Calendar and Tasks in the existing full-height drawer.
Calendar combines a Monday-first month grid and a date-grouped Agenda beneath it.
Month and year have independent arrow controls; the ghost Today icon restores
both the current month and selected date. The section's plus button creates an
event on the selected day (or a task in Tasks). Agenda starts with events overlapping
or following the selected date. The current month includes the cached upcoming
60-day window; other months end at the next month boundary, matching the fetched
range. Today and the selected day remain distinct, with event indicators in the grid.
Task views include open, due today/overdue, upcoming, important,
completed and all, with collection and text/tag filters. Future repeating tasks
remain available in Open/Upcoming. Completed recurrence exceptions are history.
Notification history has its own drawer and never changes calendar data.

Agenda and Tasks reserve one fixed-height status line immediately below their
section heading. Loading, refreshing, stale data, configuration, errors and empty
results share that slot; it stays in the layout even without a message. Text is
elided to one line, with the complete message in a tooltip, so long errors cannot
move controls or content. The editor reserves its own error line below its fixed
action toolbar and above its scrolling form. Back, Save and Delete use Lucide
icon buttons with accessible names and tooltips. Deletion uses the shared
`HoldButton`: hold the trash icon for 1.3 seconds, with a progress indicator.
Early release, focus loss, dismissal, disabling or switching the edited item
cancels the hold. The tooltip identifies when deletion affects an entire series.
No status message is inserted above the calendar or tabs.

`CalendarService` is an engine singleton started by the shell root. It warms the
current month's private disk snapshot and refreshes it quietly when due, even
before the drawer opens. Local status is checked once a minute while open and
once per 15 minutes while closed. Network snapshots have a 15-minute lifetime and
failed reads back off for five minutes; manual refresh bypasses backoff. Refresh
status does not replace the section's ordinary text while cached data is visible.

The service keeps up to 12 month snapshots in memory. Revisiting a month renders
synchronously; uncached months retain shared tasks/collections and any known event
overlap while their disk read completes. The backend reuses the cached upcoming
window when it fully covers a requested month. Tasks and collection metadata are
shared across month caches, so navigating the calendar cannot revert task edits.

Agenda and task delegates use keyed ListModels. Reconciliation inserts, removes,
moves and updates only changed records. An unchanged row retains its object,
keyboard focus and scroll context; metadata-only syncs never rebuild the list.
Task delegates load on the first Tasks visit and remain allocated through tab
switches for that drawer lifetime; Calendar opening does not create them eagerly.
Task keys include resource URL and RECURRENCE-ID, keeping completed exceptions
separate from their recurring master. Event keys include URL and occurrence time.

Actions apply an immediate in-memory overlay: completion/reopening, creation,
edits and deletion do not wait for the server. The editor closes on submission.
Writes queue for different resources; only the pending resource is disabled.
A separate serialized writer can run during a slow background reader. ETag checks
remain authoritative. Success reads back only the affected CalDAV resource and
merges its canonical values and ETag into memory and every matching disk snapshot;
there is no whole-collection refresh after ordinary successful writes. Recurring
completion uses the returned master and exception, avoiding local RRULE guessing.

Failure removes only that request's overlay, retains the last confirmed cache,
shows an error and queues quiet reconciliation. Errors lead with the failed action
and reason, followed by the item title so long titles cannot hide the cause. Failed save drafts remain in the
service and reopen in the editor, including after drawer dismissal. They are not
persisted or retried automatically. If a PUT succeeds but resource readback fails,
the optimistic row stays visible but cannot be edited until a full sync supplies
its ETag; the committed PUT is not repeated. Read generations prevent earlier
responses from undoing pending/newer changes. Queued writes carry their frozen
account identity; configuration changes cannot redirect them to another account.

`backend.py` reads feature selections from
`$XDG_CONFIG_HOME/quickshell/desktop/calendar.json`; optional arrays `calendars` and
`task_lists` match discovered collection names or slugs. Omitted means all; empty
means none. Account ownership belongs to
[`integrations`](../../integrations/ARCHITECTURE.md).

Private snapshots live in `$XDG_CACHE_HOME/quickshell/desktop/calendar/`, keyed by
account, app password file identity/revision, selections and requested month. At
most 12 months are retained; files lacking the current envelope fields are ignored.
A short process-shared publication lock protects local reads and atomic writes;
network I/O never holds it. A separate writer lock serializes DAV mutations. An
odd/even revision fences full refreshes started before or during a mutation. An
abandoned writer revision marks cached data dirty and permits authoritative
recovery without replaying the uncertain write.

Confirmed resource patches update all cached months for that account, preserving
unrelated items. Failed/uncertain writes mark snapshots dirty rather than deleting
offline data. Account/selection/credential changes select a different cache scope.
Offline reads retain last successful data, timestamps and explicit stale/error
states. Missing account, missing credential, loading, unavailable and empty results
remain distinct. There is no persistent offline mutation queue.

`caldav.py` discovers collections and privileges through PROPFIND and reads
VEVENT/VTODO resources through REPORT. Event ranges include the selected month
and current upcoming window. Resources are parsed and serialized with `icalendar`;
events expand with `recurring_ical_events` (RRULE, RDATE including periods,
EXDATE, overridden instances, Windows/Outlook TZID names). Expansion runs in
doubling windows so sub-daily rules stay bounded (2,000 occurrences per resource,
300 displayed events). Unparseable resources are skipped.
Recurring events are read-only; single events support creation, editing and
deletion, with inclusive all-day end dates in the form and exclusive DTEND on DAV.

Tasks support start/due dates and times, descriptions, location, URL, priority
0–9, progress 0–100, standard status, categories, parent relationships, recurrence,
completion/reopening and deletion. Parents must be from the same task list and
must not create an ancestry cycle. Editors keep existing items in their collection.
Ordinary property edits preserve unknown fields and nested VALARMs. All master
rewrites replace its LAST-MODIFIED property rather than appending a duplicate;
completion, reopening and recurrence snapshots share this serialization path.
Existing recurrence exceptions retain their own timestamps. Existing
alarms are preserved but alarm editing/delivery is not implemented. Collection
creation, sharing, task moves and drag ordering remain in the web client.

Task recurrence rules accept daily, weekly, monthly and yearly frequencies with
intervals, BYDAY/BYMONTHDAY and other dateutil-supported selectors, COUNT or UNTIL.
Advancing a task uses dateutil on the parsed master component.
Subdaily selectors are refused. Completing a repeating master writes one completed
RECURRENCE-ID exception and advances the master's start/due dates in the same
ETag-guarded PUT, preserving local time across DST. COUNT decrements as the master
anchor advances; the final occurrence completes the master. Exceptions keep their
UID and properties. This avoids a partially committed two-resource operation.
The editor changes the master series; its checkbox completes an occurrence.
Tasks with RDATE/EXDATE can be viewed/edited but completion belongs in Nextcloud.
Individual recurrence exceptions are read-only here. Completing a parent does
not automatically complete or advance its subtasks.

Every update/deletion rediscovers allowed writable collections, reads the resource
and checks its ETag; PUT/DELETE also send If-Match. Creates use If-None-Match: *.
No writes occur during discovery or observation. Read-only calendars stay visible.

Native notifications have their own [architecture](../notifications/ARCHITECTURE.md).

Verification from the repository root:

```sh
python3 -m unittest discover -s tests -p test_calendar_drawer.py -v
python3 -m unittest discover -s tests -p test_notification_history.py -v
python3 -m unittest discover -s tests -p test_desktop_interactions.py -v
python3 -m unittest discover -s tests -p test_generation.py -v
```

Tests use isolated account/cache roots and fake DAV responses. QML fixtures load
production drawers, filters, editor and keyboard dismissal; service fixtures cover
late month replies, writes surviving dismissal and errors. Live verification uses
only discovery and read requests; fixture tests own all remote mutation coverage.
Protocol references: [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545),
[CalDAV client operations](https://sabre.io/dav/building-a-caldav-client/).
