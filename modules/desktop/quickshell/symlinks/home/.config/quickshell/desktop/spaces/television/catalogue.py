"""IPTV-org's channel/feed identities and public HTTP streams, cached as one snapshot."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from spaces.television.storage import TelevisionError, atomic_json, http_url, read_json

DATASETS = ("channels", "streams", "feeds", "countries", "languages", "categories", "blocklist")
PAGE_SIZE = 100


def text(value, limit=500):
    return str(value or "").strip()[:limit]


def header(value):
    return text(value, 1024) if isinstance(value, str) and not any(ord(char) < 32 or ord(char) == 127 for char in value) else ""


def fetch_dataset(name):
    request = Request("https://iptv-org.github.io/api/" + name + ".json",
                      headers={"User-Agent": "QuickshellDesktop/1.0 (Television)", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=12) as response:
            body = response.read(24 * 1024 * 1024 + 1)
        if len(body) > 24 * 1024 * 1024:
            raise TelevisionError("The channel directory returned too much data.")
        result = json.loads(body)
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise ValueError()
        return result
    except (HTTPError, URLError, OSError, ValueError):
        raise TelevisionError("The channel directory is unavailable. Saved channels remain usable.") from None


def stream_record(raw, feed=None):
    url = http_url(raw.get("url"))
    if not url:
        return None
    user_agent, referrer = header(raw.get("user_agent")), http_url(raw.get("referrer"))
    identity = hashlib.sha256(json.dumps([url, user_agent, referrer]).encode()).hexdigest()[:24]
    quality = text(raw.get("quality"), 40)
    feed = feed or {}
    labels = [text(value, 80) for value in raw.get("labels", [])[:8]] if isinstance(raw.get("labels", []), list) else []
    return dict(id=identity, url=url, quality=quality, feed=text(feed.get("name"), 100),
                labels=labels, user_agent=user_agent, referrer=referrer)


def normalize(data):
    channels = {text(row.get("id")): row for row in data["channels"] if row.get("id")}
    countries = {text(row.get("code")): text(row.get("name")) for row in data["countries"]}
    languages = {text(row.get("code")): text(row.get("name")) for row in data["languages"]}
    categories = {text(row.get("id")): text(row.get("name")) for row in data["categories"]}
    blocked = {text(row.get("channel")) for row in data["blocklist"]}
    feeds, main_feeds = {}, {}
    for row in data["feeds"]:
        feeds[(row.get("channel"), row.get("id"))] = row
        if row.get("is_main"): main_feeds.setdefault(row.get("channel"), row)
    grouped = {}
    for raw in data["streams"]:
        channel_id = text(raw.get("channel"))
        metadata = channels.get(channel_id, {})
        if channel_id in blocked or metadata.get("is_nsfw") or metadata.get("closed"):
            continue
        feed = feeds.get((raw.get("channel"), raw.get("feed")), main_feeds.get(raw.get("channel"), {}))
        stream = stream_record(raw, feed)
        if stream is None:
            continue
        # Unidentified public streams still have a stable URL identity and title.
        identity = channel_id or "stream:" + stream["id"]
        name = text(metadata.get("name") or raw.get("title"))
        if not name:
            continue
        if identity not in grouped:
            country = text(metadata.get("country"), 2)
            codes = [code for code in metadata.get("categories", []) if code in categories] if isinstance(metadata.get("categories", []), list) else []
            grouped[identity] = dict(id=identity, name=name, aliases=metadata.get("alt_names") or [], country=country,
                countryName=countries.get(country, ""), categories=codes, categoryNames=[categories[code] for code in codes],
                languages=[], languageNames=[], website=http_url(metadata.get("website")), streams=[])
        channel = grouped[identity]
        if not any(value["id"] == stream["id"] for value in channel["streams"]):
            channel["streams"].append(stream)
        for code in feed.get("languages", []) if isinstance(feed.get("languages", []), list) else []:
            if code in languages and code not in channel["languages"]:
                channel["languages"].append(code); channel["languageNames"].append(languages[code])
    result = list(grouped.values())
    for channel in result:
        def rank(stream):
            match = re.search(r"\d+", stream["quality"])
            return ("Geo-blocked" in stream["labels"], -(int(match[0]) if match else 0), stream["feed"], stream["id"])
        channel["streams"].sort(key=rank)
    result.sort(key=lambda row: (row["name"].casefold(), row["country"], row["id"]))
    def options(field, names):
        used = {code for channel in result for code in channel[field]}
        return sorted([dict(code=code, name=names[code]) for code in used if code in names], key=lambda row: row["name"].casefold())
    country_codes = {channel["country"] for channel in result if channel["country"]}
    filters = dict(countries=sorted([dict(code=code, name=countries.get(code, code)) for code in country_codes], key=lambda row: row["name"].casefold()),
                   languages=options("languages", languages), categories=options("categories", categories))
    return dict(channels=result, filters=filters, updated=int(time.time()))


class Catalogue:
    def __init__(self, cache, fetch=fetch_dataset):
        self.path = cache / "catalogue.json"
        self.fetch = fetch
        self.refresh_lock = threading.Lock()
        try:
            self.snapshot = read_json(self.path, {})
        except TelevisionError:
            self.snapshot = {}  # Catalogue data is regenerable; private records are not.
        if not isinstance(self.snapshot, dict) or not isinstance(self.snapshot.get("channels", []), list):
            self.snapshot = {}

    def summary(self):
        return dict(total=len(self.snapshot.get("channels", [])), filters=self.snapshot.get("filters", {}),
                    updated=self.snapshot.get("updated", 0), stale=time.time() - self.snapshot.get("updated", 0) > 86400)

    def refresh(self):
        with self.refresh_lock:
            try:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    data = dict(zip(DATASETS, pool.map(self.fetch, DATASETS)))
                snapshot = normalize(data)
                if not snapshot["channels"]:
                    raise TelevisionError("The channel directory returned no usable channels. Saved data was preserved.")
                atomic_json(self.path, snapshot)
                self.snapshot = snapshot
                return dict(self.summary(), warning="")
            except TelevisionError:
                if self.snapshot.get("channels"):
                    return dict(self.summary(), warning="Offline: using the saved channel directory.")
                raise

    def browse(self, request, favorites):
        snapshot = self.snapshot
        rows = snapshot.get("channels", [])
        by_id = {row["id"]: row for row in rows}
        favorite_ids = {row["id"] for row in favorites}
        if request.get("favorites"):
            rows = [by_id.get(row["id"], row) for row in favorites]
        else:
            rows = sorted(rows, key=lambda row: row["id"] not in favorite_ids)
        query = text(request.get("query")).casefold()
        country, language, category = (text(request.get(key)) for key in ("country", "language", "category"))
        def matches(row):
            haystack = " ".join([row["name"], *row.get("aliases", []), row.get("countryName", ""), *row.get("languageNames", []), *row.get("categoryNames", [])]).casefold()
            return (not query or query in haystack) and (not country or row.get("country") == country) and (not language or language in row.get("languages", [])) and (not category or category in row.get("categories", []))
        rows = [row for row in rows if matches(row)]
        try: offset = max(0, int(request.get("offset") or 0))
        except (ValueError, TypeError): offset = 0
        return dict(items=rows[offset:offset+PAGE_SIZE], nextOffset=offset+PAGE_SIZE if offset+PAGE_SIZE < len(rows) else -1, total=len(rows))
