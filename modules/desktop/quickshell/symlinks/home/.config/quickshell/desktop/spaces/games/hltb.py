"""Bounded public HowLongToBeat reads with explicit, conservative title matching."""
import json
import math
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BASE = "https://howlongtobeat.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": BASE + "/",
    "Origin": BASE,
    "Content-Type": "application/json",
}


class HltbError(RuntimeError):
    pass


def game_id(value):
    text = str(value or "").strip()
    if text.isdigit() and 0 < int(text) < 10000000:
        return str(int(text))
    parsed = urllib.parse.urlsplit(text)
    match = re.fullmatch(r"/game/(\d+)/?", parsed.path)
    if (parsed.scheme == "https" and parsed.netloc == "howlongtobeat.com"
            and match and not parsed.query and not parsed.fragment):
        return game_id(match[1])
    raise HltbError("Enter a HowLongToBeat game link or numeric ID, or leave it blank for automatic matching.")


def normalize(record):
    identifier = game_id(record.get("game_id"))
    result = {"id": identifier, "title": str(record.get("game_name", ""))[:200],
              "url": BASE + "/game/" + identifier}
    for name, field in (("main", "comp_main"), ("extras", "comp_plus"), ("complete", "comp_100")):
        seconds = record.get(field)
        result[name] = round(seconds / 3600, 1) if (
            type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds < 360000000
        ) else None
    return result


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.data = []
        self.in_data = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.in_data = attrs.get("id") == "__NEXT_DATA__"
            if attrs.get("src"):
                self.scripts.append(attrs["src"])

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_data = False

    def handle_data(self, data):
        if self.in_data:
            self.data.append(data)


class Client:
    def __init__(self, transport=None):
        self.transport = transport or self.read
        self.lock = threading.Lock()
        self.auth = None
        self.endpoint = "/api/search/site"

    @staticmethod
    def read(path, body=None, headers=None):
        url = urllib.parse.urljoin(BASE, path)
        if urllib.parse.urlsplit(url).netloc != "howlongtobeat.com":
            raise HltbError("Invalid HowLongToBeat request.")
        request = urllib.request.Request(url, data=body, headers={**HEADERS, **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise HltbError("HowLongToBeat returned too much data.")
            return data.decode("utf-8")
        except (OSError, ValueError, UnicodeError, urllib.error.URLError):
            raise HltbError("HowLongToBeat is unavailable. Saved times are still available offline.") from None

    def discover(self):
        page = Page()
        page.feed(self.transport("/"))
        for source in page.scripts[:12]:
            parsed = urllib.parse.urlsplit(urllib.parse.urljoin(BASE, source))
            if parsed.netloc != "howlongtobeat.com" or not parsed.path.endswith(".js"):
                continue
            script = self.transport(parsed.path)
            if "searchTerms" not in script or "searchOptions" not in script:
                continue
            paths = re.findall(r'["\'`](/api/[A-Za-z0-9_/]+)["\'`]', script)
            for path in paths:
                if path.endswith("/init"):
                    self.endpoint = path[:-5]
                    return

    def search(self, title):
        with self.lock:
            for attempt in range(2):
                try:
                    if not self.auth:
                        auth = json.loads(self.transport(self.endpoint + "/init"))
                        if not isinstance(auth, dict) or not isinstance(auth.get("token"), str):
                            raise HltbError("HowLongToBeat search is unavailable.")
                        self.auth = auth
                    headers = {"x-auth-token": self.auth["token"]}
                    body = {
                        "searchType": "games", "searchTerms": title.split(), "searchPage": 1, "size": 20,
                        "searchOptions": {"games": {"userId": 0, "platform": "", "sortCategory": "name",
                            "rangeCategory": "main", "rangeTime": {"min": 0, "max": 0},
                            "gameplay": {"perspective": "", "flow": "", "genre": "", "difficulty": ""},
                            "modifier": "hide_dlc"}, "users": {}, "filter": "", "sort": 0, "randomizer": 0},
                    }
                    key = next((value for name, value in self.auth.items() if "key" in name.lower() and isinstance(value, str)), "")
                    value = next((value for name, value in self.auth.items() if "val" in name.lower() and isinstance(value, str)), "")
                    if key and value:
                        headers.update({"x-hp-key": key, "x-hp-val": value})
                        body[key] = value
                    result = json.loads(self.transport(self.endpoint, json.dumps(body).encode(), headers))
                    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                        raise HltbError("HowLongToBeat returned an unreadable result.")
                    return [row for row in result["data"][:20] if isinstance(row, dict)]
                except (HltbError, ValueError, TypeError, KeyError):
                    self.auth = None
                    if attempt:
                        raise HltbError("HowLongToBeat search is unavailable. Try a direct game link.") from None
                    self.discover()

    def details(self, identifier):
        identifier = game_id(identifier)
        page = Page()
        page.feed(self.transport("/game/" + identifier))
        try:
            data = json.loads("".join(page.data))
            records = data["props"]["pageProps"]["game"]["data"]["game"]
            record = next(row for row in records if str(row.get("game_id")) == identifier)
            return record
        except (ValueError, KeyError, TypeError, StopIteration):
            raise HltbError("HowLongToBeat could not read that game page.") from None

    def lookup(self, title, steam_id="", override="", title_key=lambda value: value.casefold()):
        if override:
            return normalize(self.details(override))
        rows = self.search(title)
        exact = [row for row in rows if title_key(str(row.get("game_name", ""))) == title_key(title)]
        steam = [row for row in rows if steam_id and str(row.get("profile_steam")) == steam_id]
        candidates = steam or exact
        if len(candidates) != 1:
            return {"main": None, "extras": None, "complete": None,
                    "warning": "No unique match. Set a HowLongToBeat game link to choose the correct edition."}
        record = candidates[0]
        if steam_id and record.get("profile_steam") and str(record["profile_steam"]) != steam_id:
            return {"warning": "The HowLongToBeat result belongs to a different Steam game. Set a game link."}
        return normalize(record)
