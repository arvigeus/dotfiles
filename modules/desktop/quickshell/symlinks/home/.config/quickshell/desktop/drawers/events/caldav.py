"""Nextcloud CalDAV: discover collections, read events and tasks, edit events and rich tasks."""

import copy
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote, unquote, urljoin
from uuid import uuid4

import recurring_ical_events
from dateutil import tz
from dateutil.rrule import rrulestr
from icalendar import Calendar, Event, Todo, vDDDTypes, vRecur

from integrations.nextcloud import DAVClient, NextcloudError

DAV = "DAV:"
CAL = "urn:ietf:params:xml:ns:caldav"
NS = {"d": DAV, "c": CAL}


class Client(DAVClient):
    def __init__(self, config, *, opener=None):
        scope = "remote.php/dav/calendars/" + quote(config.get("username", ""), safe="") + "/"
        super().__init__(config, scope=scope, opener=opener)

    def propfind(self):
        body = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:displayname/><d:resourcetype/><c:supported-calendar-component-set/><d:current-user-privilege-set/></d:prop>
</d:propfind>"""
        raw, _ = self.request(
            "PROPFIND",
            self.home,
            body,
            {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
        )
        try:
            document = ET.fromstring(raw)
        except ET.ParseError as error:
            raise NextcloudError("Nextcloud returned invalid calendar discovery data.") from error
        collections = []
        for response in document.findall("d:response", NS):
            href = response.findtext("d:href", default="", namespaces=NS)
            url = urljoin(self.base, href)
            if url.rstrip("/") == self.home.rstrip("/") or not url.startswith(self.home):
                continue
            for propstat in response.findall("d:propstat", NS):
                if " 200 " not in propstat.findtext("d:status", default="", namespaces=NS):
                    continue
                prop = propstat.find("d:prop", NS)
                if prop is None or prop.find("d:resourcetype/c:calendar", NS) is None:
                    continue
                components = {
                    node.get("name")
                    for node in prop.findall("c:supported-calendar-component-set/c:comp", NS)
                }
                privileges = {
                    node.tag.rsplit("}", 1)[-1]
                    for node in prop.findall("d:current-user-privilege-set/d:privilege/*", NS)
                }
                collections.append(
                    {
                        "url": url,
                        "slug": unquote(url.rstrip("/").rsplit("/", 1)[-1]),
                        "name": prop.findtext("d:displayname", default="", namespaces=NS)
                        or unquote(url.rstrip("/").rsplit("/", 1)[-1]),
                        "components": components or {"VEVENT", "VTODO"},
                        "writable": bool({"write", "write-content", "all"} & privileges)
                        and bool({"bind", "all"} & privileges),
                    }
                )
        return collections

    def report(self, collection, kind, start=None, end=None):
        time_range = ""
        if start and end:
            time_range = '<c:time-range start="' + start + '" end="' + end + '"/>'
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="'
            + kind
            + '">'
            + time_range
            + "</c:comp-filter></c:comp-filter></c:filter>"
            "</c:calendar-query>"
        ).encode()
        raw, _ = self.request(
            "REPORT",
            collection["url"],
            body,
            {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
        )
        try:
            document = ET.fromstring(raw)
        except ET.ParseError as error:
            raise NextcloudError("Nextcloud returned invalid calendar data.") from error
        entries = []
        for response in document.findall("d:response", NS):
            href = response.findtext("d:href", default="", namespaces=NS)
            for propstat in response.findall("d:propstat", NS):
                if " 200 " not in propstat.findtext("d:status", default="", namespaces=NS):
                    continue
                prop = propstat.find("d:prop", NS)
                if prop is None:
                    continue
                data = prop.findtext("c:calendar-data", default="", namespaces=NS)
                if data:
                    entries.append(
                        (
                            urljoin(self.base, href),
                            prop.findtext("d:getetag", default="", namespaces=NS),
                            data,
                        )
                    )
        return entries

    def checked_item(self, config, kind, entry):
        """Fetch an existing item from a selected writable collection, guarded by its ETag."""
        collection = next((row for row in self.propfind()
            if row["slug"] == entry.get("collection") and kind in row["components"]
            and row["writable"] and chosen(row, selection(config, "task_lists" if kind == "VTODO" else "calendars"))), None)
        href, etag = entry.get("href", ""), entry.get("etag", "")
        if not collection or not href or not etag or not href.startswith(collection["url"]):
            raise NextcloudError("Choose a writable collection and refresh this item.")
        raw, headers = self.request("GET", href)
        if headers.get("ETag") != etag:
            raise NextcloudError("This item changed on Nextcloud. Refresh and try again.")
        self.item_collection = collection
        return parse(raw)

    def put(self, href, calendar, etag=None):
        guard = {"If-Match": etag} if etag else {"If-None-Match": "*"}
        self.request("PUT", href, calendar.to_ical(sorted=False),
                     {"Content-Type": "text/calendar; charset=utf-8", **guard})

    def set_completed(self, config, entry, completed):
        calendar = self.checked_item(config, "VTODO", entry)
        master = master_of(calendar, "VTODO")
        if completed and "RRULE" in master:
            advance_task(calendar, master)
        else:
            update(master, completion_fields(completed), COMPLETION)
        self.put(entry["href"], calendar, entry["etag"])
        return {"saved": True, "href": entry["href"], "collection": self.item_collection}

    def delete_item(self, config, kind, entry):
        self.checked_item(config, kind, entry)
        self.request("DELETE", entry["href"], headers={"If-Match": entry["etag"]})
        return {"deleted": True, "href": entry["href"], "collection": self.item_collection}

    def check_parent(self, collection, entry):
        parents = {}
        for _, _, resource in self.report(collection, "VTODO"):
            try:
                todos = Calendar.from_ical(resource).walk("VTODO")
            except ValueError:
                continue
            for todo in todos:
                if "RECURRENCE-ID" not in todo:
                    parents[text(todo, "UID")] = text(todo, "RELATED-TO")
        parent = entry["parent"]
        if parent not in parents:
            raise NextcloudError("Choose a parent from this task list.")
        visited = {entry.get("uid")} if entry.get("uid") else set()
        while parent:
            if parent in visited:
                raise NextcloudError("A task cannot be its own ancestor.")
            visited.add(parent)
            parent = parents.get(parent, "")

    def save_item(self, config, kind, entry):
        if kind not in ("VTODO", "VEVENT") or not isinstance(entry, dict):
            raise NextcloudError("The calendar item is invalid.")
        slug = str(entry.get("collection", ""))
        selected = selection(config, "task_lists" if kind == "VTODO" else "calendars")
        collection = next((item for item in self.propfind() if item["slug"] == slug and kind in item["components"]
                           and item["writable"] and chosen(item, selected)), None)
        if collection is None:
            raise NextcloudError("Choose a writable calendar or task list.")
        if kind == "VTODO" and entry.get("parent"):
            self.check_parent(collection, entry)
        fields = entry_fields(kind, entry)
        href, etag = str(entry.get("href", "")), str(entry.get("etag", ""))
        if not href:
            identity = uuid4().hex
            fields.add("UID", identity + "@desktop")
            fields.add("DTSTAMP", now())
            calendar = Calendar()
            calendar.add("VERSION", "2.0")
            calendar.add("PRODID", "-//Desktop//Calendar//EN")
            calendar.add_component(fields)
            href = collection["url"] + identity + ".ics"
            self.put(href, calendar)
            return {"saved": True, "href": href, "collection": collection}
        if not href.startswith(collection["url"]) or not etag:
            raise NextcloudError("This item cannot be updated. Refresh and try again.")
        raw, headers = self.request("GET", href)
        if headers.get("ETag") != etag:
            raise NextcloudError("This item changed on Nextcloud. Refresh and try again.")
        calendar = parse(raw)
        master = master_of(calendar, kind)
        if kind == "VTODO":
            if str(fields.get("STATUS")) == "COMPLETED" and "RRULE" in master:
                raise NextcloudError("Use the task checkbox to complete a recurring occurrence.")
            preserve_task_dates(master, fields)
            owned = TASK_FIELDS | ({"DURATION"} if "DUE" in fields else set())
        else:
            owned = EVENT_FIELDS
        update(master, fields, owned)
        self.put(href, calendar, etag)
        return {"saved": True, "href": href, "collection": collection}


COMPLETION = {"STATUS", "PERCENT-COMPLETE", "COMPLETED"}
TASK_FIELDS = {"SUMMARY", "DESCRIPTION", "DUE", "DTSTART", "PRIORITY", "CATEGORIES", "RELATED-TO",
               "LOCATION", "URL", "RRULE"} | COMPLETION
EVENT_FIELDS = {"SUMMARY", "DESCRIPTION", "DTSTART", "DTEND", "DURATION", "LOCATION", "URL"}


def now():
    return datetime.now(UTC).replace(microsecond=0)


def parse(data):
    try:
        return Calendar.from_ical(data)
    except ValueError as error:
        raise NextcloudError("Nextcloud returned an invalid calendar item.") from error


def master_of(calendar, kind):
    """The single editable component; recurring events and grouped items belong to Nextcloud."""
    if kind == "VTODO":
        records = [item for item in calendar.walk(kind) if "RECURRENCE-ID" not in item]
    else:
        records = calendar.walk(kind)
    if len(records) != 1:
        raise NextcloudError("Recurring or grouped items must be edited in Nextcloud.")
    if kind == "VEVENT" and any(key in records[0] for key in ("RRULE", "RDATE", "RECURRENCE-ID")):
        raise NextcloudError("Recurring items must be edited in Nextcloud.")
    return records[0]


def update(component, fields, owned):
    """Replace owned properties and LAST-MODIFIED; unknown properties and alarms stay."""
    for name in {*owned, *fields, "LAST-MODIFIED"}:
        component.pop(name, None)
    for name, value in fields.items():
        component[name] = value
    component.add("LAST-MODIFIED", now())


def one(component, name):
    value = component.get(name)
    return value[0] if isinstance(value, list) else value


def text(component, name):
    value = one(component, name)
    return "" if value is None else str(value)


def aware(value, zone):
    """DATE values start at local midnight; floating times use the local zone."""
    if not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    return value if value.tzinfo else value.replace(tzinfo=zone)


def moment(component, name, zone):
    """(aware datetime | None, is_date) for a DATE or DATE-TIME property."""
    value = one(component, name)
    if value is None:
        return None, False
    return aware(value.dt, zone), not isinstance(value.dt, datetime)


def moved(prop, value):
    """A copy of a DATE/DATE-TIME property with a new value and the original TZID/VALUE."""
    result = vDDDTypes(value)
    result.params = copy.deepcopy(prop.params)
    return result


def selection(config, key):
    value = config.get(key)
    if value is not None and not isinstance(value, list):
        raise NextcloudError(f"{key} in calendar.json must be a list or omitted.")
    if value is not None and any(not isinstance(name, str) for name in value):
        raise NextcloudError(f"{key} in calendar.json must contain collection names.")
    return value


def chosen(collection, selected):
    """An omitted selection includes everything; entries match a name or CalDAV slug."""
    return selected is None or collection["slug"] in selected or collection["name"] in selected


def plain(value):
    return str(value).replace("\r", "")


def task_date(day, clock=""):
    """A DATE, or a local wall time stored as UTC, from editor fields."""
    if not day:
        if clock:
            raise ValueError()
        return None
    value = date.fromisoformat(day)
    if not clock:
        return value
    return datetime.combine(value, datetime.strptime(clock, "%H:%M").time()).astimezone(UTC)


def completion_fields(completed):
    fields = Todo()
    fields.add("STATUS", "COMPLETED" if completed else "NEEDS-ACTION")
    fields.add("PERCENT-COMPLETE", 100 if completed else 0)
    if completed:
        fields.add("COMPLETED", now())
    return fields


def entry_fields(kind, entry):
    """Validate editor input into a detached component holding the owned properties."""
    title = str(entry.get("summary", "")).strip()
    description = str(entry.get("description", "")).strip()
    if not title or len(title) > 250 or len(description) > 10000:
        raise NextcloudError(
            "Enter a title of at most 250 characters and notes of at most 10,000 characters."
        )
    fields = Todo() if kind == "VTODO" else Event()
    fields.add("SUMMARY", plain(title))
    if entry.get("location"):
        fields.add("LOCATION", plain(entry["location"]))
    if entry.get("url"):
        url = str(entry["url"])
        if "\r" in url or "\n" in url:
            raise NextcloudError("The item URL must be a single line.")
        fields.add("URL", url)
    if description:
        fields.add("DESCRIPTION", plain(description))
    local = tz.gettz()
    try:
        if kind == "VTODO":
            start = task_date(entry.get("start_date", ""), entry.get("start_time", ""))
            due = task_date(entry.get("due", ""), entry.get("due_time", ""))
            if start is not None:
                fields.add("DTSTART", start)
            if due is not None:
                fields.add("DUE", due)
            if start is not None and due is not None and aware(due, local) < aware(start, local):
                raise ValueError()
            priority = int(entry.get("priority", 0))
            percent = int(entry.get("percent", 0))
            status = entry.get("status", "NEEDS-ACTION")
            if not 0 <= priority <= 9 or not 0 <= percent <= 100:
                raise ValueError()
            if status not in ("NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED"):
                raise ValueError()
            fields.add("PRIORITY", priority)
            if status == "COMPLETED" or percent == 100:
                fields.update(completion_fields(True))
            else:
                fields.add("STATUS", status)
                fields.add("PERCENT-COMPLETE", percent)
            tags = [plain(tag).strip() for tag in str(entry.get("categories", "")).split(",") if tag.strip()]
            if tags:
                fields.add("CATEGORIES", tags)
            if entry.get("parent"):
                fields.add("RELATED-TO", plain(entry["parent"]), parameters={"RELTYPE": "PARENT"})
            rule = str(entry.get("recurrence_rule", "")).strip().upper()
            if rule:
                anchor = due if due is not None else start
                if anchor is None or "\n" in rule or "\r" in rule or len(rule) > 1000:
                    raise ValueError()
                parsed = vRecur.from_ical(rule)
                recurrence(parsed, aware(anchor, local))
                fields.add("RRULE", parsed)
            return fields
        starts = date.fromisoformat(str(entry.get("start_date", "")))
        ends = date.fromisoformat(str(entry.get("end_date", "")))
        if entry.get("all_day"):
            if ends < starts:
                raise ValueError()
            # DAV DTEND is exclusive; the form's all-day end date is inclusive.
            fields.add("DTSTART", starts)
            fields.add("DTEND", ends + timedelta(days=1))
            return fields
        # Naive astimezone() applies the local zone's offset for that date, DST included.
        start_at = datetime.combine(starts, datetime.strptime(str(entry.get("start_time", "")), "%H:%M").time()).astimezone()
        end_at = datetime.combine(ends, datetime.strptime(str(entry.get("end_time", "")), "%H:%M").time()).astimezone()
        if end_at <= start_at:
            raise ValueError()
        fields.add("DTSTART", start_at.astimezone(UTC))
        fields.add("DTEND", end_at.astimezone(UTC))
        return fields
    except NextcloudError:
        raise
    except (ValueError, OverflowError) as error:
        raise NextcloudError(
            "Check the date and time. Use YYYY-MM-DD and HH:MM, with the end after the start."
        ) from error


def preserve_task_dates(master, fields):
    """Keep the task's TZID/floating semantics when the editor submits local wall time."""
    local = tz.gettz()
    for key in ("DTSTART", "DUE"):
        previous, current = one(master, key), fields.get(key)
        if previous is None or current is None:
            continue
        before, after = previous.dt, current.dt
        was_day, is_day = not isinstance(before, datetime), not isinstance(after, datetime)
        if was_day == is_day and (aware(before, local).replace(second=0, microsecond=0)
                                  == aware(after, local).replace(second=0, microsecond=0)):
            fields[key] = copy.deepcopy(previous)
        elif not was_day and not is_day and (previous.params.get("TZID") or before.tzinfo is None):
            shifted = after.astimezone(before.tzinfo or local)
            fields[key] = moved(previous, shifted if before.tzinfo else shifted.replace(tzinfo=None))


def recurrence(rule, anchor):
    """dateutil expansion of a task rule, limited to calendar frequencies."""
    if rule.get("FREQ") not in (["DAILY"], ["WEEKLY"], ["MONTHLY"], ["YEARLY"]) or ("COUNT" in rule and "UNTIL" in rule):
        raise NextcloudError("Use a daily, weekly, monthly or yearly recurrence rule.")
    if int(rule.get("INTERVAL", [1])[0]) < 1 or int(rule.get("COUNT", [1])[0]) < 1:
        raise NextcloudError("Recurrence intervals and counts must be positive.")
    if any(key in rule for key in ("BYSECOND", "BYMINUTE", "BYHOUR")):
        raise NextcloudError("Set the task time separately from its recurrence rule.")
    if "UNTIL" in rule:
        # dateutil needs a UTC UNTIL with an aware start; RFC 5545 also allows DATE/local values.
        rule = copy.deepcopy(rule)
        until = rule["UNTIL"][0]
        if not isinstance(until, datetime):
            until = datetime.combine(until, datetime.max.time().replace(microsecond=0))
        rule["UNTIL"] = [aware(until, anchor.tzinfo).astimezone(UTC)]
    return rrulestr(rule.to_ical().decode(), dtstart=anchor)


def advance_task(calendar, master):
    """Complete this occurrence and advance the master, for one ETag-guarded PUT.

    The completed exception joins the same resource with the master's UID, unknown
    properties and alarms. COUNT decrements because the master's anchor advances.
    """
    if "RDATE" in master or "EXDATE" in master:
        raise NextcloudError("Complete tasks with additional recurrence dates in Nextcloud.")
    local = tz.gettz()
    anchor_key = "DUE" if "DUE" in master else "DTSTART"
    anchor, _ = moment(master, anchor_key, local)
    if not anchor:
        raise NextcloudError("Recurring tasks need a start or due date.")
    rule = copy.deepcopy(one(master, "RRULE"))
    following = recurrence(rule, anchor).after(anchor, inc=False)
    if following is None:
        update(master, completion_fields(True), COMPLETION)
        return
    exception = copy.deepcopy(master)
    exception["RECURRENCE-ID"] = copy.deepcopy(one(master, anchor_key))
    update(exception, completion_fields(True), {"RRULE", *COMPLETION})
    # Same-zone arithmetic keeps the local time across DST changes.
    delta = following - anchor
    fields = completion_fields(False)
    for key in ("DUE", "DTSTART"):
        if key in master:
            prop = one(master, key)
            fields[key] = moved(prop, prop.dt + delta)
    if "COUNT" in rule:
        rule["COUNT"] = [max(1, int(rule["COUNT"][0]) - 1)]
    fields["RRULE"] = rule
    update(master, fields, {"DUE", "DTSTART", "RRULE", *COMPLETION})
    calendar.add_component(exception)


def resources(entries):
    for href, etag, ics in entries:
        try:
            yield href, etag, Calendar.from_ical(ics)
        except ValueError:
            continue


def expand(calendar, start, end, local_zone, limit=2000):
    """(occurrence, start, is_date) overlapping [start, end); recurrence overrides replace
    their instance. Doubling windows keep sub-daily rules from expanding without bound."""
    query = recurring_ical_events.of(calendar, components=["VEVENT"])
    lower, span, found = start, timedelta(days=1), 0
    while lower < end and found < limit:
        upper = min(lower + span, end)
        for occurrence in query.between(lower, upper):
            begins, all_day = moment(occurrence, "DTSTART", local_zone)
            # Windows are half-open; anything starting earlier was already returned.
            if (lower == start or begins >= lower) and found < limit:
                found += 1
                yield occurrence, begins, all_day
        lower, span = upper, span * 2


def events_from(entries, collection, start, end, local_zone):
    results = []
    for href, etag, calendar in resources(entries):
        records = calendar.walk("VEVENT")
        editable = bool(collection.get("writable")) and len(records) == 1 and not any(
            key in records[0] for key in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID"))
        try:
            for occurrence, begins, all_day in expand(calendar, start, end, local_zone):
                if text(occurrence, "STATUS").upper() == "CANCELLED":
                    continue
                finishes, _ = moment(occurrence, "DTEND", local_zone)
                if not finishes or finishes <= begins:
                    finishes = begins + (timedelta(days=1) if all_day else timedelta(hours=1))
                if finishes <= start:
                    continue
                results.append({
                    "summary": text(occurrence, "SUMMARY") or "Untitled event",
                    "start": begins.isoformat(), "end": finishes.isoformat(),
                    "date": begins.astimezone(local_zone).date().isoformat(),
                    "last_date": (finishes - timedelta(microseconds=1)).astimezone(local_zone).date().isoformat(),
                    "all_day": all_day,
                    "calendar": collection["name"], "calendar_slug": collection.get("slug", ""),
                    "href": href, "etag": etag,
                    "description": text(occurrence, "DESCRIPTION"),
                    "location": text(occurrence, "LOCATION"), "url": text(occurrence, "URL"),
                    "editable": editable,
                })
        except (ValueError, TypeError, OverflowError):
            continue
    return results


def tasks_from(entries, collection, local_zone):
    results = []
    for href, etag, calendar in resources(entries):
        for todo in calendar.walk("VTODO"):
            try:
                due, all_day = moment(todo, "DUE", local_zone)
                begins, start_day = moment(todo, "DTSTART", local_zone)
                percent = int(todo.get("PERCENT-COMPLETE", 0))
                priority = int(todo.get("PRIORITY", 0))
            except (ValueError, TypeError, AttributeError):
                continue
            status = text(todo, "STATUS") or "NEEDS-ACTION"
            rule = one(todo, "RRULE")
            occurrence = one(todo, "RECURRENCE-ID")
            categories = todo.get("CATEGORIES", [])
            # Grouped exceptions remain visible as history; edits target only the master.
            editable = bool(collection.get("writable", False)) and occurrence is None
            results.append({
                "summary": text(todo, "SUMMARY") or "Untitled task",
                "due": due.astimezone(local_zone).date().isoformat() if due else "",
                "due_time": due.astimezone(local_zone).strftime("%H:%M") if due and not all_day else "",
                "start_date": begins.astimezone(local_zone).date().isoformat() if begins else "",
                "start_time": begins.astimezone(local_zone).strftime("%H:%M") if begins and not start_day else "",
                "list": collection["name"], "list_slug": collection.get("slug", ""),
                "description": text(todo, "DESCRIPTION"),
                "href": href, "etag": etag, "uid": text(todo, "UID"),
                "parent": text(todo, "RELATED-TO"),
                "categories": ", ".join(str(tag) for prop in (categories if isinstance(categories, list) else [categories])
                                        for tag in prop.cats),
                "location": text(todo, "LOCATION"), "url": text(todo, "URL"),
                "priority": priority, "percent": percent, "status": status,
                "completed": status == "COMPLETED" or percent == 100,
                "recurring": rule is not None, "recurrence_rule": rule.to_ical().decode() if rule is not None else "",
                "exception": occurrence is not None,
                "recurrence_id": occurrence.to_ical().decode() if occurrence is not None else "",
                "actionable": editable and "RDATE" not in todo and "EXDATE" not in todo,
                "editable": editable,
            })
    return results


def snapshot(config, *, start=None, end=None, opener=None):
    """Collections, events for the requested range plus the upcoming window, and open tasks."""
    client = Client(config, opener=opener)
    local_zone = tz.gettz()
    today = date.today()
    current_window = (today - timedelta(days=7), today + timedelta(days=60))
    target_window = (
        (date.fromisoformat(start), date.fromisoformat(end)) if start and end else current_window
    )
    if target_window[1] <= target_window[0] or (target_window[1] - target_window[0]).days > 180:
        raise NextcloudError("The calendar date range is invalid.")
    combined = (min(current_window[0], target_window[0]), max(current_window[1], target_window[1]))
    windows = (
        [combined] if (combined[1] - combined[0]).days <= 180 else [current_window, target_window]
    )
    calendar_selection = selection(config, "calendars")
    task_selection = selection(config, "task_lists")

    events, tasks = [], []
    collections = client.propfind()
    for collection in collections:
        if "VEVENT" in collection["components"] and chosen(collection, calendar_selection):
            for range_start, range_end in windows:
                lower = datetime.combine(range_start, datetime.min.time(), tzinfo=local_zone)
                upper = datetime.combine(range_end, datetime.min.time(), tzinfo=local_zone)
                query_start = (lower - timedelta(days=1)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
                query_end = (upper + timedelta(days=1)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
                entries = client.report(collection, "VEVENT", query_start, query_end)
                events.extend(events_from(entries, collection, lower, upper, local_zone))
        if "VTODO" in collection["components"] and chosen(collection, task_selection):
            entries = client.report(collection, "VTODO")
            tasks.extend(tasks_from(entries, collection, local_zone))
    events = list({(event["href"], event["start"]): event for event in events}.values())
    events.sort(key=lambda event: event["start"])
    tasks.sort(key=lambda task: (task["due"] == "", task["due"], task["summary"].casefold()))
    return {
        "calendars": [
            {
                "name": item["name"],
                "slug": item["slug"],
                "components": sorted(item["components"]),
                "writable": item.get("writable", False),
                "events_enabled": chosen(item, calendar_selection),
                "tasks_enabled": chosen(item, task_selection),
            }
            for item in collections
        ],
        "events": events[:300],
        "tasks": tasks,
        "task_count": sum(not task["completed"] for task in tasks),
    }
