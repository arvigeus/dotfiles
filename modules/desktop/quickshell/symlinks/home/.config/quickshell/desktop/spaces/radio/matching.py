"""Conservative URL matching and cached catalogue metadata for cloud favorites."""
import hashlib
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, urlunsplit

from spaces.radio import api
from spaces.radio.storage import atomic_json, read_json, http_url


def endpoint(value):
    parsed = urlsplit(http_url(value))
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if port and port not in (80, 443): host += ":" + str(port)
    return host + (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")


def site(value):
    return (urlsplit(http_url(value)).hostname or "").lower().removeprefix("www.")


def station_name(value):
    return re.sub(r"\s*[\(\[]\s*(?:(?:aac\+?|mp3|ogg|opus|flac)\s*(?:\d+(?:\s*kbps)?)?|\d+\s*kbps)\s*[\)\]]\s*$", "", value, flags=re.I).strip()


def public_lookup(value):
    parsed = urlsplit(value)
    # Never publish an authenticated private stream address to a public catalogue.
    return not parsed.username and not parsed.password and not parsed.query


class RadioMatcher:
    def __init__(self, cache=None):
        self.cache = Path(cache) if cache else Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "quickshell/desktop/spaces/radio/matches"

    def match(self, remote, preferred_uuid=None):
        stream = remote["streamUrl"]
        key = hashlib.sha256((stream + "|" + (preferred_uuid or "")).encode()).hexdigest()
        path = self.cache / (key + ".json")
        cached = read_json(path, {})
        if isinstance(cached, dict) and time.time() - cached.get("checked", 0) < 86400:
            return cached.get("record")
        rows = []
        if preferred_uuid:
            rows = api.api_get("/json/stations/byuuid", {"uuids": preferred_uuid})
        elif public_lookup(stream):
            rows = api.api_get("/json/stations/byurl", {"url": stream})
            if not rows:
                parsed = urlsplit(stream)
                alternate = urlunsplit(("http" if parsed.scheme == "https" else "https", parsed.netloc, parsed.path, "", ""))
                rows = api.api_get("/json/stations/byurl", {"url": alternate})
        if not isinstance(rows, list):
            raise api.RadioError("The station directory returned invalid match results.")
        if not preferred_uuid:
            rows = [row for row in rows if isinstance(row, dict) and any(endpoint(row.get(key)) == endpoint(stream) for key in ("url", "url_resolved"))]
        rows = [row for row in rows if isinstance(row, dict) and api.station_record(row)]
        if not rows:
            atomic_json(path, dict(checked=time.time(), record=None))
            return None
        rows.sort(key=lambda row: (bool(row.get("lastcheckok")), api.safe_int(row.get("clickcount")), api.safe_int(row.get("bitrate"))), reverse=True)
        chosen = rows[0]
        name = station_name(chosen["name"])
        related = api.api_get("/json/stations/search", {"name": name,
            "countrycode": chosen.get("countrycode", ""), "limit": 100, "hidebroken": "true"})
        candidates = rows + (related if isinstance(related, list) else [])
        records = {}
        for row in candidates:
            if not isinstance(row, dict) or not api.station_record(row): continue
            same_station = (bool(site(chosen.get("homepage")))
                            and str(row.get("countrycode", "")).upper() == str(chosen.get("countrycode", "")).upper()
                            and site(row.get("homepage")) == site(chosen.get("homepage"))
                            and station_name(row.get("name", "")).casefold() == name.casefold())
            if row["stationuuid"] != chosen["stationuuid"] and not same_station: continue
            if row["stationuuid"] != chosen["stationuuid"] and not row.get("lastcheckok"): continue
            record = api.station_record(row)
            record.update(name=name, homepage=chosen.get("homepage") or record["homepage"])
            records[record["stationuuid"]] = (record, bool(row.get("lastcheckok")))
        ordered = sorted(records.values(), key=lambda pair: (pair[1], pair[0]["bitrate"], pair[0]["clickcount"]), reverse=True)
        record = dict(ordered[0][0], variants=[pair[0] for pair in ordered])
        if not any(pair[1] for pair in ordered):
            # A known catalogue identity can still enrich an unavailable station.
            # Keep the user's stream rather than replacing it with a broken one.
            fallback = dict(record, url=stream, url_resolved=stream, source="nextcloud", codec="", bitrate=0)
            fallback.pop("variants", None)
            record = dict(fallback, variants=[dict(fallback)])
        payload = dict(checked=time.time(), record=record)
        atomic_json(path, payload)
        canonical = record.get("url_resolved") or record["url"]
        canonical_key = hashlib.sha256((canonical + "|" + record["stationuuid"]).encode()).hexdigest()
        if canonical_key != key:
            atomic_json(self.cache / (canonical_key + ".json"), payload)
        return record
