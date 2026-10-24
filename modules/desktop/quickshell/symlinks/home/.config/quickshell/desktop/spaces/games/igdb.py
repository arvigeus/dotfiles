"""IGDB v4 adapter: OAuth, request pacing and a provider-independent game record.

API contract: https://api-docs.igdb.com/ . Credentials never leave this adapter.
"""

import json
import re
import threading
import time
import urllib.parse
from datetime import UTC, datetime

from spaces.games import gog

BROWSE_FIELDS = "name,summary,cover.image_id,screenshots.image_id,artworks.image_id,genres.name,platforms.name,first_release_date,total_rating,total_rating_count,websites.url,websites.type"
DETAIL_FIELDS = (
    BROWSE_FIELDS
    + ",themes.name,involved_companies.company.name,involved_companies.developer,involved_companies.publisher,franchises.name,collections.name,dlcs.name,expansions.name,parent_game.name"
)


def image(record, size="screenshot_big"):
    identifier = (record or {}).get("image_id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(identifier)):
        return None
    return {
        "url": f"https://images.igdb.com/igdb/image/upload/t_{size}/{identifier}.jpg",
        "thumbnail": f"https://images.igdb.com/igdb/image/upload/t_screenshot_med/{identifier}.jpg",
    }


def official_website(websites):
    for site in websites:
        if not isinstance(site, dict) or str(site.get("type")) != "1":
            continue
        url = str(site.get("url") or "").strip()
        if not url or len(url) > 2048:
            continue
        try:
            parsed = urllib.parse.urlsplit(url)
            if (
                parsed.scheme in ("http", "https")
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and parsed.port in (None, 80, 443)
            ):
                return url
        except ValueError:
            continue
    return ""


def normalize(raw, game_id=""):
    identifier = int(raw["id"])
    if identifier <= 0 or not raw.get("name"):
        raise ValueError("Invalid IGDB game")

    def names(key):
        return list(
            dict.fromkeys(
                v["name"] for v in raw.get(key, []) if isinstance(v, dict) and v.get("name")
            )
        )

    companies = raw.get("involved_companies", [])
    references = []
    websites = raw.get("websites") or []
    for site in websites:
        if not isinstance(site, dict):
            continue
        try:
            parsed = urllib.parse.urlsplit(str(site.get("url") or ""))
        except ValueError:
            continue
        match = re.match(r"/app/([1-9][0-9]*)\b", parsed.path)
        if (
            parsed.scheme == "https"
            and not parsed.username
            and parsed.hostname == "store.steampowered.com"
            and match
        ):
            app_id = match.group(1)
            references.append(
                {
                    "store": "steam",
                    "externalId": app_id,
                    "url": f"https://store.steampowered.com/app/{app_id}/",
                }
            )
        if parsed.scheme == "https" and not parsed.username:
            if parsed.hostname == "store.epicgames.com":
                epic = re.fullmatch(
                    r"/(?:[a-z]{2}-[A-Z]{2}/)?p/([A-Za-z0-9][A-Za-z0-9_.-]*)/?", parsed.path
                )
            elif parsed.hostname == "www.epicgames.com":
                epic = re.fullmatch(
                    r"/store/[a-z]{2}-[A-Z]{2}/product/([A-Za-z0-9][A-Za-z0-9_.-]*)/(?:home/?)?",
                    parsed.path,
                )
            else:
                epic = None
            if epic:
                references.append(
                    {
                        "store": "epic",
                        "externalId": epic.group(1),
                        "url": f"https://{parsed.hostname}{parsed.path}",
                    }
                )
            if slug := gog.store_slug(site.get("url")):
                references.append({"store": "gog", "externalId": slug,
                                   "url": gog.store_url(site["url"])})
    release = (
        datetime.fromtimestamp(raw["first_release_date"], UTC).strftime("%Y-%m-%d")
        if raw.get("first_release_date")
        else ""
    )
    relationships = [
        {"type": kind, "title": entry["name"]}
        for key, kind in (("dlcs", "dlc"), ("expansions", "expansion"))
        for entry in raw.get(key, [])
        if isinstance(entry, dict) and entry.get("name")
    ]
    if isinstance(raw.get("parent_game"), dict) and raw["parent_game"].get("name"):
        relationships.append({"type": "parent", "title": raw["parent_game"]["name"]})
    return {
        "id": game_id,
        "catalogProvider": "igdb",
        "catalogProviderId": str(identifier),
        "title": raw["name"],
        "summary": raw.get("summary", ""),
        "cover": image(raw.get("cover"), "cover_big"),
        "artwork": [v for r in raw.get("artworks", [])[:12] if (v := image(r))],
        "screenshots": [v for r in raw.get("screenshots", [])[:32] if (v := image(r))],
        "genres": names("genres"),
        "themes": names("themes"),
        "platforms": names("platforms"),
        "developers": list(
            dict.fromkeys(
                c["company"]["name"]
                for c in companies
                if c.get("developer") and c.get("company", {}).get("name")
            )
        ),
        "publishers": list(
            dict.fromkeys(
                c["company"]["name"]
                for c in companies
                if c.get("publisher") and c.get("company", {}).get("name")
            )
        ),
        "releaseDate": release,
        "releases": [{"date": release, "platform": "", "region": ""}] if release else [],
        "franchises": names("franchises"),
        "collections": names("collections"),
        "relationships": relationships,
        "storeReferences": references,
        "officialWebsite": official_website(websites),
        "rating": round(raw["total_rating"] / 20, 2)
        if raw.get("total_rating") is not None
        else None,
        "ratingCount": raw.get("total_rating_count", 0),
    }


class Client:
    def __init__(self, config, request, error_type=RuntimeError):
        self.config, self.request, self.error = config, request, error_type
        self.lock = threading.Lock()
        self.token = ""
        self.expires = 0
        self.credentials = None
        self.last_request = 0
        self.cooldown = 0

    def credentials_pair(self):
        config = self.config()
        return str(config.get("igdb_client_id", "")).strip(), str(
            config.get("igdb_client_secret", "")
        ).strip()

    def _authenticate(self):
        credentials = self.credentials_pair()
        if not all(credentials):
            raise self.error(
                "Add igdb_client_id and igdb_client_secret to games.json to browse games."
            )
        if credentials == self.credentials and self.token and time.monotonic() < self.expires:
            return
        body = urllib.parse.urlencode(
            dict(
                client_id=credentials[0],
                client_secret=credentials[1],
                grant_type="client_credentials",
            )
        ).encode()
        try:
            result = self.request(
                "https://id.twitch.tv/oauth2/token",
                "POST",
                {"Content-Type": "application/x-www-form-urlencoded"},
                body,
                12,
                65536,
            )
            self.token = result["access_token"]
            self.expires = time.monotonic() + max(0, int(result["expires_in"]) - 60)
            self.credentials = credentials
        except Exception:
            raise self.error(
                "IGDB authentication failed. Check the credentials in games.json and your connection."
            ) from None

    def query(self, endpoint, body):
        # Serializing provider calls keeps both OAuth refresh and the four-per-second
        # budget correct. Library scanning and UI work run on separate worker lanes.
        with self.lock:
            if time.monotonic() < self.cooldown:
                raise self.error("IGDB is temporarily unavailable. Try again shortly.")
            for attempt in range(2):
                self._authenticate()
                assert self.credentials is not None
                time.sleep(max(0, 0.26 - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                try:
                    result = self.request(
                        "https://api.igdb.com/v4/" + endpoint,
                        "POST",
                        {
                            "Client-ID": self.credentials[0],
                            "Authorization": "Bearer " + self.token,
                            "Accept": "application/json",
                            "Content-Type": "text/plain",
                        },
                        body.encode(),
                        15,
                        4 * 1024 * 1024,
                    )
                    if not isinstance(result, list):
                        raise self.error("IGDB returned an invalid response.")
                    return result
                except self.error as error:
                    if "HTTP 401" in str(error) and not attempt:
                        self.token = ""
                        continue
                    self.cooldown = time.monotonic() + 15
                    raise self.error(
                        "IGDB could not load this request. Try again shortly."
                    ) from None

    def browse(self, query, filters, offset, limit):
        conditions = []
        for key in ("genres", "platforms"):
            if filters.get(key):
                conditions.append(f"{key} = ({int(filters[key])})")
        if filters.get("dates"):
            low, high = filters["dates"].split(",")
            conditions.extend(
                [
                    f"first_release_date >= {int(datetime.fromisoformat(low).replace(tzinfo=UTC).timestamp())}",
                    f"first_release_date <= {int(datetime.fromisoformat(high).replace(hour=23, minute=59, second=59, tzinfo=UTC).timestamp())}",
                ]
            )
        body = f"fields {BROWSE_FIELDS}; limit {limit}; offset {offset};"
        if conditions:
            body += " where " + " & ".join(conditions) + ";"
        if query:
            body += " search " + json.dumps(query) + ";"
        else:
            ordering = {
                "-added": "total_rating_count desc",
                "-rating": "total_rating desc",
                "-released": "first_release_date desc",
                "-updated": "updated_at desc",
                "name": "name asc",
                "-metacritic": "aggregated_rating desc",
            }
            body += " sort " + ordering[filters["ordering"]] + ";"
        return self.query("games", body)

    def details(self, identifier):
        rows = self.query(
            "games", f"fields {DETAIL_FIELDS}; where id = {int(identifier)}; limit 1;"
        )
        return rows[0] if rows else None

    def filters(self):
        return {
            endpoint: self.query(endpoint, "fields name; sort name asc; limit 500;")
            for endpoint in ("genres", "platforms")
        }
