"""Nextcloud CalDAV: discover collections, read events and tasks, edit events and rich tasks."""

import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote, unquote, urljoin
from uuid import uuid4
from itertools import islice
from zoneinfo import ZoneInfo

from dateutil import tz
from dateutil.rrule import rrulestr

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

    def rewrite(self, href, etag, kind, fields, replace):
        """Replace owned properties of the master, guarded by its ETag."""
        if not href or not etag:
            raise NextcloudError("This item cannot be updated. Refresh and try again.")
        raw, headers = self.request("GET", href)
        if headers.get("ETag") != etag:
            raise NextcloudError("This item changed on Nextcloud. Refresh and try again.")
        data = raw.decode("utf-8")
        if kind == "VTODO":
            fields = preserve_task_dates(data, fields)
        updated = update_ical(data, kind, fields, replace)
        if kind == "VTODO" and any(field == "STATUS:COMPLETED" for field in fields):
            props = next(props for name, props in components(data) if name == kind and "RECURRENCE-ID" not in props)
            if first(props, "RRULE")[1]:
                raise NextcloudError("Use the task checkbox to complete a recurring occurrence.")
        self.request(
            "PUT",
            href,
            updated,
            {"Content-Type": "text/calendar; charset=utf-8", "If-Match": etag},
        )

    def checked_item(self, config, kind, entry):
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
        return raw.decode("utf-8")

    def set_completed(self, config, entry, completed):
        data = self.checked_item(config, "VTODO", entry)
        records = [props for name, props in components(data) if name == "VTODO" and "RECURRENCE-ID" not in props]
        if len(records) != 1:
            raise NextcloudError("This grouped task must be edited in Nextcloud.")
        props = records[0]
        fields = completion_fields(completed)
        replace = {"STATUS", "PERCENT-COMPLETE", "COMPLETED"}
        if completed and first(props, "RRULE")[1]:
            data = advance_task(data, props)
        else:
            data = update_ical(data, "VTODO", fields, replace).decode()
        self.request("PUT", entry["href"], data.encode(),
                     {"Content-Type": "text/calendar; charset=utf-8", "If-Match": entry["etag"]})
        return {"saved": True, "href": entry["href"], "collection": self.item_collection}

    def delete_item(self, config, kind, entry):
        self.checked_item(config, kind, entry)
        self.request("DELETE", entry["href"], headers={"If-Match": entry["etag"]})
        return {"deleted": True, "href": entry["href"], "collection": self.item_collection}

    def save_item(self, config, kind, entry):
        if kind not in ("VTODO", "VEVENT") or not isinstance(entry, dict):
            raise NextcloudError("The calendar item is invalid.")
        slug = str(entry.get("collection", ""))
        selected = selection(config, "task_lists" if kind == "VTODO" else "calendars")
        collection = next(
            (
                item
                for item in self.propfind()
                if item["slug"] == slug
                and kind in item["components"]
                and item["writable"]
                and chosen(item, selected)
            ),
            None,
        )
        if collection is None:
            raise NextcloudError("Choose a writable calendar or task list.")
        if kind == "VTODO" and entry.get("parent"):
            parents = {}
            for _, _, resource in self.report(collection, "VTODO"):
                for component, props in components(resource):
                    if component == "VTODO" and "RECURRENCE-ID" not in props:
                        parents[first(props, "UID")[1]] = first(props, "RELATED-TO")[1]
            parent = entry["parent"]
            if parent not in parents:
                raise NextcloudError("Choose a parent from this task list.")
            visited = {entry.get("uid")} if entry.get("uid") else set()
            while parent:
                if parent in visited: raise NextcloudError("A task cannot be its own ancestor.")
                visited.add(parent)
                parent = parents.get(parent, "")
        fields = entry_fields(kind, entry)
        href = str(entry.get("href", ""))
        if href:
            if not href.startswith(collection["url"]):
                raise NextcloudError("This item cannot be updated. Refresh and try again.")
            replace = (
                {"SUMMARY", "DESCRIPTION", "DUE", "DTSTART", "PRIORITY", "PERCENT-COMPLETE", "STATUS", "COMPLETED", "CATEGORIES", "RELATED-TO", "LOCATION", "URL", "RRULE"}
                | ({"DURATION"} if any(field.startswith("DUE") for field in fields) else set())
                if kind == "VTODO"
                else {"SUMMARY", "DESCRIPTION", "DTSTART", "DTEND", "DURATION", "LOCATION", "URL"}
            )
            self.rewrite(href, str(entry.get("etag", "")), kind, fields, replace)
            return {"saved": True, "href": href, "collection": collection}
        identity = uuid4().hex
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Desktop//Calendar//EN",
            "BEGIN:" + kind,
            "UID:" + identity + "@desktop",
            "DTSTAMP:" + stamp,
            *fields,
            "END:" + kind,
            "END:VCALENDAR",
        ]
        self.request(
            "PUT",
            collection["url"] + identity + ".ics",
            serialize_ical(lines),
            {"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"},
        )
        return {"saved": True, "href": collection["url"] + identity + ".ics", "collection": collection}


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


def escape_text(value):
    return (
        str(value).replace("\r", "")
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def entry_fields(kind, entry):
    title = str(entry.get("summary", "")).strip()
    description = str(entry.get("description", "")).strip()
    if not title or len(title) > 250 or len(description) > 10000:
        raise NextcloudError(
            "Enter a title of at most 250 characters and notes of at most 10,000 characters."
        )
    fields = ["SUMMARY:" + escape_text(title)]
    if entry.get("location"):
        fields.append("LOCATION:" + escape_text(entry["location"]))
    if entry.get("url"):
        url = str(entry["url"])
        if "\r" in url or "\n" in url:
            raise NextcloudError("The item URL must be a single line.")
        fields.append("URL:" + url)
    if description:
        fields.append("DESCRIPTION:" + escape_text(description))
    try:
        if kind == "VTODO":
            start = task_date_field("DTSTART", entry.get("start_date", ""), entry.get("start_time", ""))
            due = task_date_field("DUE", entry.get("due", ""), entry.get("due_time", ""))
            if start: fields.append(start)
            if due: fields.append(due)
            if start and due:
                begins, _ = date_value(first(dict(components("BEGIN:VTODO\n" + start + "\nEND:VTODO"))["VTODO"], "DTSTART"), tz.gettz())
                ends, _ = date_value(first(dict(components("BEGIN:VTODO\n" + due + "\nEND:VTODO"))["VTODO"], "DUE"), tz.gettz())
                if ends < begins: raise ValueError()
            priority = int(entry.get("priority", 0))
            percent = int(entry.get("percent", 0))
            if not 0 <= priority <= 9 or not 0 <= percent <= 100: raise ValueError()
            status = entry.get("status", "NEEDS-ACTION")
            if status not in ("NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED"): raise ValueError()
            fields.extend(["PRIORITY:" + str(priority), "PERCENT-COMPLETE:" + str(percent), "STATUS:" + status])
            if status == "COMPLETED" or percent == 100:
                fields = [f for f in fields if not f.startswith(("STATUS:", "PERCENT-COMPLETE:"))] + completion_fields(True)
            if entry.get("categories"):
                fields.append("CATEGORIES:" + ",".join(escape_text(tag.strip()) for tag in entry["categories"].split(",") if tag.strip()))
            if entry.get("parent"):
                fields.append("RELATED-TO;RELTYPE=PARENT:" + escape_text(entry["parent"]))
            rule = str(entry.get("recurrence_rule", "")).strip().upper()
            if rule:
                if not (start or due) or "\n" in rule or "\r" in rule or len(rule) > 1000: raise ValueError()
                anchor, _ = date_value(({}, (due or start).split(":", 1)[1]), tz.gettz())
                validate_rule(rule, anchor)
                fields.append("RRULE:" + rule)
            return fields
        starts = date.fromisoformat(str(entry.get("start_date", "")))
        ends = date.fromisoformat(str(entry.get("end_date", "")))
        if entry.get("all_day"):
            if ends < starts:
                raise ValueError()
            return [
                *fields,
                "DTSTART;VALUE=DATE:" + starts.strftime("%Y%m%d"),
                "DTEND;VALUE=DATE:" + (ends + timedelta(days=1)).strftime("%Y%m%d"),
            ]
        # Naive astimezone() applies the local zone's offset for that date, DST included.
        start_at = datetime.combine(
            starts, datetime.strptime(str(entry.get("start_time", "")), "%H:%M").time()
        ).astimezone()
        end_at = datetime.combine(
            ends, datetime.strptime(str(entry.get("end_time", "")), "%H:%M").time()
        ).astimezone()
        if end_at <= start_at:
            raise ValueError()
        return [
            *fields,
            "DTSTART:" + start_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"),
            "DTEND:" + end_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"),
        ]
    except (ValueError, OverflowError) as error:
        raise NextcloudError(
            "Check the date and time. Use YYYY-MM-DD and HH:MM, with the end after the start."
        ) from error


def unfold_ical(data):
    lines = []
    for line in data.splitlines():
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def serialize_ical(lines):
    folded = []
    for line in lines:
        current = ""
        for character in line:
            if len((current + character).encode("utf-8")) > 75:
                folded.append(current)
                current = " " + character
            else:
                current += character
        folded.append(current)
    return ("\r\n".join(folded) + "\r\n").encode("utf-8")


def update_ical(data, kind, fields, replace):
    """Replace owned master properties, including its modification timestamp."""
    replace = set(replace) | {"LAST-MODIFIED"}
    lines = unfold_ical(data)
    opening, closing = "BEGIN:" + kind, "END:" + kind
    starts = []
    for index, line in enumerate(lines):
        if line.upper() != opening: continue
        tail = lines[index + 1:]
        stop = tail.index(closing) if closing in tail else len(tail)
        if kind == "VTODO" and any(value.upper().startswith("RECURRENCE-ID") for value in tail[:stop]): continue
        starts.append(index)
    if len(starts) != 1:
        raise NextcloudError("Recurring or grouped items must be edited in Nextcloud.")
    start = starts[0]
    try:
        end = lines.index(closing, start + 1)
    except ValueError as error:
        raise NextcloudError("Nextcloud returned an invalid calendar item.") from error
    depth = 0
    kept = []
    for line in lines[start + 1 : end]:
        key = line.split(":", 1)[0].split(";", 1)[0].upper()
        if depth == 0 and ((kind == "VEVENT" and key in ("RRULE", "RDATE", "RECURRENCE-ID")) or key == "RECURRENCE-ID"):
            raise NextcloudError("Recurring items must be edited in Nextcloud.")
        if depth == 0 and key in replace:
            continue
        kept.append(line)
        if key == "BEGIN":
            depth += 1
        elif key == "END":
            depth -= 1
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines[start + 1 : end] = [*kept, *fields, "LAST-MODIFIED:" + stamp]
    return serialize_ical(lines)


def components(ics):
    """Return (name, {PROPERTY: [(params, value)]}) for each VEVENT and VTODO."""
    stack = []
    found = []
    for line in unfold_ical(ics):
        if line.startswith("BEGIN:"):
            stack.append((line[6:].upper(), {}))
        elif line.startswith("END:"):
            if not stack:
                continue
            name, props = stack.pop()
            if name in ("VEVENT", "VTODO"):
                found.append((name, props))
        elif stack and stack[-1][0] in ("VEVENT", "VTODO") and ":" in line:
            head, value = line.split(":", 1)
            name, *options = head.split(";")
            params = dict(option.split("=", 1) for option in options if "=" in option)
            stack[-1][1].setdefault(name.upper(), []).append((params, value))
    return found


def first(props, key):
    return props.get(key, [({}, "")])[0]


def text_value(value):
    # One pass, so an escaped backslash followed by "n" stays literal.
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m[1] in "nN" else m[1], value)


def cancelled(props):
    return first(props, "STATUS")[1].upper() == "CANCELLED"


def date_value(field, local_zone):
    """Parse a DATE or DATE-TIME property; returns (aware datetime | None, is_date)."""
    params, value = field
    if not value:
        return None, False
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        return datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=local_zone), True
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC), False
    zone = local_zone
    if params.get("TZID"):
        try:
            zone = ZoneInfo(params["TZID"].strip('"'))
        except (KeyError, ValueError):
            pass
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=zone), False


def utc_until(rule, zone):
    """dateutil requires a UTC UNTIL with an aware DTSTART; RFC 5545 allows DATE/local values."""

    def convert(match):
        moment, is_date = date_value(({}, match.group(1)), zone)
        if is_date:
            moment += timedelta(days=1, seconds=-1)
        return "UNTIL=" + moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    return re.sub(r"(?i)UNTIL=([0-9]{8}(?:T[0-9]{6}Z?)?)", convert, rule)


def span(props, local_zone):
    begins, all_day = date_value(first(props, "DTSTART"), local_zone)
    if not begins:
        return None
    finishes, _ = date_value(first(props, "DTEND"), local_zone)
    default = timedelta(days=1) if all_day else timedelta(hours=1)
    duration = finishes - begins if finishes and finishes > begins else default
    if not finishes and first(props, "DURATION")[1]:
        match = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", first(props, "DURATION")[1])
        if match:
            weeks, days, hours, minutes, seconds = (int(value or 0) for value in match.groups())
            duration = timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds) or default
    return begins, duration, all_day


def events_from(entries, collection, start, end, local_zone):
    """Expand events overlapping [start, end); recurrence overrides replace their instance."""
    results = []

    def add(props, href, etag, begins, finishes, all_day, editable):
        if not (begins < end and finishes > start):
            return
        results.append(
            {
                "summary": text_value(first(props, "SUMMARY")[1]) or "Untitled event",
                "start": begins.isoformat(),
                "end": finishes.isoformat(),
                "date": begins.astimezone(local_zone).date().isoformat(),
                "last_date": (finishes - timedelta(microseconds=1))
                .astimezone(local_zone)
                .date()
                .isoformat(),
                "all_day": all_day,
                "calendar": collection["name"],
                "calendar_slug": collection.get("slug", ""),
                "href": href,
                "etag": etag,
                "description": text_value(first(props, "DESCRIPTION")[1]),
                "location": text_value(first(props, "LOCATION")[1]),
                "url": text_value(first(props, "URL")[1]),
                "editable": editable,
            }
        )

    for href, etag, ics in entries:
        records = [props for kind, props in components(ics) if kind == "VEVENT"]
        overridden = set()
        for props in records:
            if "RECURRENCE-ID" not in props:
                continue
            try:
                moment, _ = date_value(first(props, "RECURRENCE-ID"), local_zone)
                parsed = span(props, local_zone)
            except ValueError:
                continue
            if moment:
                overridden.add(moment.timestamp())
            if parsed and not cancelled(props):
                begins, duration, all_day = parsed
                add(props, href, etag, begins, begins + duration, all_day, False)
        for props in records:
            if "RECURRENCE-ID" in props or cancelled(props):
                continue
            rule = first(props, "RRULE")[1]
            try:
                parsed = span(props, local_zone)
                if not parsed:
                    continue
                begins, duration, all_day = parsed
                occurrences = [begins]
                if rule:
                    expanded = rrulestr(utc_until(rule, begins.tzinfo), dtstart=begins)
                    occurrences = list(islice(expanded.xafter(start - duration, inc=True), 2000))
                    occurrences = [moment for moment in occurrences if moment < end]
                for params, values in props.get("RDATE", []):
                    occurrences.extend(date_value((params, value), local_zone)[0] for value in values.split(","))
                occurrences = list(set(occurrences))
                excluded = {
                    moment.timestamp()
                    for params, values in props.get("EXDATE", [])
                    for value in values.split(",")
                    if (moment := date_value((params, value), local_zone)[0])
                }
            except ValueError:
                continue
            editable = bool(collection.get("writable")) and not any(k in props for k in ("RRULE", "RDATE", "EXDATE"))
            skipped = overridden | excluded
            for occurrence in occurrences:
                if occurrence.timestamp() not in skipped:
                    add(props, href, etag, occurrence, occurrence + duration, all_day, editable)
    return results


def tasks_from(entries, collection, local_zone):
    results = []
    for href, etag, ics in entries:
        for kind, props in components(ics):
            if kind != "VTODO": continue
            try:
                due, all_day = date_value(first(props, "DUE"), local_zone)
                begins, start_day = date_value(first(props, "DTSTART"), local_zone)
                status = first(props, "STATUS")[1] or "NEEDS-ACTION"
                percent = int(first(props, "PERCENT-COMPLETE")[1] or 0)
                priority = int(first(props, "PRIORITY")[1] or 0)
            except ValueError:
                continue
            rule = first(props, "RRULE")[1]
            exception = bool(first(props, "RECURRENCE-ID")[1])
            # Grouped exceptions remain visible as history; edits target only the master.
            editable = bool(collection.get("writable", False)) and not exception
            actionable = editable and not any(key in props for key in ("RDATE", "EXDATE"))
            results.append({
                "summary": text_value(first(props, "SUMMARY")[1]) or "Untitled task",
                "due": due.astimezone(local_zone).date().isoformat() if due else "",
                "due_time": due.astimezone(local_zone).strftime("%H:%M") if due and not all_day else "",
                "start_date": begins.astimezone(local_zone).date().isoformat() if begins else "",
                "start_time": begins.astimezone(local_zone).strftime("%H:%M") if begins and not start_day else "",
                "list": collection["name"], "list_slug": collection.get("slug", ""),
                "description": text_value(first(props, "DESCRIPTION")[1]),
                "href": href, "etag": etag, "uid": first(props, "UID")[1],
                "parent": first(props, "RELATED-TO")[1],
                "categories": ", ".join(text_value(value) for _, value in props.get("CATEGORIES", [])),
                "location": text_value(first(props, "LOCATION")[1]), "url": text_value(first(props, "URL")[1]),
                "priority": priority, "percent": percent, "status": status,
                "completed": status == "COMPLETED" or percent == 100,
                "recurring": bool(rule), "recurrence_rule": rule,
                "exception": exception, "recurrence_id": first(props, "RECURRENCE-ID")[1], "actionable": actionable, "editable": editable,
            })
    return results


def preserve_task_dates(data, fields):
    """Keep the task's TZID/floating semantics when editing in local wall time."""
    props = next((props for kind, props in components(data) if kind == "VTODO" and "RECURRENCE-ID" not in props), {})
    result = []
    for field in fields:
        head, value = field.split(":", 1)
        key = head.split(";", 1)[0]
        if key not in ("DTSTART", "DUE") or not first(props, key)[1]:
            result.append(field)
            continue
        original, was_day = date_value(first(props, key), tz.gettz())
        current, is_day = date_value(({"VALUE": "DATE"} if ";VALUE=DATE" in head else {}, value), tz.gettz())
        params, previous = first(props, key)
        if was_day == is_day and original.replace(second=0, microsecond=0) == current.replace(second=0, microsecond=0):
            value = previous
        elif not was_day and not is_day and (params.get("TZID") or not previous.endswith("Z")):
            value = current.astimezone(original.tzinfo).strftime("%Y%m%dT%H%M%S")
        else:
            result.append(field)
            continue
        suffix = ";" + ";".join(k + "=" + v for k, v in params.items()) if params else ""
        result.append(key + suffix + ":" + value)
    return result


def task_date_field(key, day, clock=""):
    if not day:
        if clock: raise ValueError()
        return ""
    value = date.fromisoformat(day)
    if not clock: return key + ";VALUE=DATE:" + value.strftime("%Y%m%d")
    value = datetime.combine(value, datetime.strptime(clock, "%H:%M").time()).astimezone(UTC)
    return key + ":" + value.strftime("%Y%m%dT%H%M%SZ")


def completion_fields(completed):
    if not completed: return ["STATUS:NEEDS-ACTION", "PERCENT-COMPLETE:0"]
    return ["STATUS:COMPLETED", "PERCENT-COMPLETE:100", "COMPLETED:" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")]


def validate_rule(rule, anchor):
    # Bound expansion to calendar frequencies; prevent pathological subsecond rules.
    parts = rule.split(";")
    settings = dict(part.split("=", 1) for part in parts if "=" in part)
    if len(settings) != len(parts) or settings.get("FREQ") not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        raise NextcloudError("Use a daily, weekly, monthly or yearly recurrence rule.")
    if int(settings.get("INTERVAL", 1)) < 1 or ("COUNT" in settings and int(settings["COUNT"]) < 1):
        raise NextcloudError("Recurrence intervals and counts must be positive.")
    if "COUNT" in settings and "UNTIL" in settings:
        raise NextcloudError("Use a daily, weekly, monthly or yearly recurrence rule.")
    if any(part.startswith(("BYSECOND=", "BYMINUTE=", "BYHOUR=")) for part in rule.split(";")):
        raise NextcloudError("Set the task time separately from its recurrence rule.")
    return rrulestr(utc_until(rule, anchor.tzinfo), dtstart=anchor)


def advance_task(data, props):
    """Complete this occurrence and advance the master in one ETag-guarded PUT.

    Keep an exception in the same resource, preserving the UID and unknown fields.
    COUNT is decremented because the master's recurrence anchor advances.
    """
    if any(key in props for key in ("RDATE", "EXDATE")):
        raise NextcloudError("Complete tasks with additional recurrence dates in Nextcloud.")
    anchor_key = "DUE" if first(props, "DUE")[1] else "DTSTART"
    anchor, _ = date_value(first(props, anchor_key), tz.gettz())
    if not anchor: raise NextcloudError("Recurring tasks need a start or due date.")
    rule = first(props, "RRULE")[1]
    expanded = validate_rule(rule, anchor)
    following = expanded.after(anchor, inc=False)
    if following is None:
        return update_ical(data, "VTODO", completion_fields(True), {"STATUS", "PERCENT-COMPLETE", "COMPLETED"}).decode()
    delta = following - anchor
    fields = completion_fields(False)
    for key in ("DUE", "DTSTART"):
        params, value = first(props, key)
        if not value: continue
        moment, is_day = date_value((params, value), tz.gettz())
        next_date = moment + delta
        suffix = ";" + ";".join(k + "=" + v for k, v in params.items()) if params else ""
        formatted = next_date.strftime("%Y%m%d" if is_day else "%Y%m%dT%H%M%SZ" if value.endswith("Z") else "%Y%m%dT%H%M%S")
        fields.append(key + suffix + ":" + formatted)
    rule = re.sub(r"COUNT=(\d+)", lambda m: "COUNT=" + str(max(1, int(m[1]) - 1)), rule)
    fields.append("RRULE:" + rule)
    # Snapshot the original component as an exception, without altering its alarms.
    original = unfold_ical(data)
    first_task = next(index for index, line in enumerate(original) if line == "BEGIN:VTODO"
        and not any(value.startswith("RECURRENCE-ID") for value in original[index + 1:original.index("END:VTODO", index)]))
    last_task = original.index("END:VTODO", first_task)
    exception = original[first_task:last_task + 1]
    exception = update_ical("\r\n".join(exception), "VTODO", completion_fields(True),
                            {"RRULE", "STATUS", "PERCENT-COMPLETE", "COMPLETED"}).decode()
    exception_lines = unfold_ical(exception)
    params, value = first(props, anchor_key)
    suffix = ";" + ";".join(k + "=" + v for k, v in params.items()) if params else ""
    exception_lines.insert(-1, "RECURRENCE-ID" + suffix + ":" + value)
    updated = unfold_ical(update_ical(data, "VTODO", fields, {"DUE", "DTSTART", "RRULE", "STATUS", "PERCENT-COMPLETE", "COMPLETED"}).decode())
    updated[updated.index("END:VCALENDAR"):updated.index("END:VCALENDAR")] = exception_lines
    return serialize_ical(updated).decode()


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
