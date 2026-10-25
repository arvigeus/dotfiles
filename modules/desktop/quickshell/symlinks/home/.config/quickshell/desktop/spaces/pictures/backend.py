"""Pictures providers, favorites, and desktop wallpaper worker."""

import argparse
import json
import os
import random
import re
import sys
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spaces.pictures import providers as command_providers
from spaces.pictures import video_wallpaper, wallpaper_engine
from spaces.pictures.storage import atomic_write

API_ROOT = "https://wallhaven.cc/api/v1"
BING_FEED_ROOT = "https://www.bing.com/HPImageArchive.aspx"
USER_AGENT = "Desktop-Pictures/1.0"
MAX_IMAGE_BYTES = 250 * 1024 * 1024
WALLPAPER_DOWNLOAD_SECONDS = 60
BING_CACHE_SECONDS = 900
BING_CATALOG_CACHE = {}
WALLHAVEN_TAG_CACHE = {}
WALLHAVEN_ID = re.compile(r"^[A-Za-z0-9]{4,16}$")
ALLOWED_CATEGORIES = {"111", "100", "010", "001"}
ALLOWED_PURITY = {"100", "110"}
ALLOWED_SORTING = {"toplist", "date_added", "views", "favorites", "hot", "relevance", "random"}
ALLOWED_RANGES = {"1d", "3d", "1w", "1M", "3M", "6M", "1y"}
ALLOWED_RATIOS = {"16x9", "16x10", "21x9", "32x9", "9x16", "10x16", "1x1", "3x2", "4x3", "5x4"}
ALLOWED_RESOLUTIONS = {"", "1920x1080", "2560x1440", "3840x2160"}
BING_MARKETS = {
    "US": "en-US",
    "GB": "en-GB",
    "CA": "en-CA",
    "AU": "en-AU",
    "IN": "en-IN",
    "VN": "vi-VN",
    "DE": "de-DE",
    "FR": "fr-FR",
    "ES": "es-ES",
    "IT": "it-IT",
    "JP": "ja-JP",
    "BR": "pt-BR",
    "MX": "es-MX",
}
PROVIDERS = {
    "wallhaven": {
        "id": "wallhaven",
        "name": "Wallhaven",
        "random": True,
        "search": True,
        "defaultFilters": {
            "categories": "111",
            "sorting": "hot",
            "topRange": "1M",
            "ratio": "",
            "resolution": "",
            "tagQuery": "",
        },
        "filters": [
            {
                "key": "categories",
                "label": "Category",
                "width": 138,
                "options": [
                    {"label": "All categories", "value": "111"},
                    {"label": "General", "value": "100"},
                    {"label": "Anime", "value": "010"},
                    {"label": "People", "value": "001"},
                ],
            },
            {
                "key": "tagQuery",
                "label": "Any tag",
                "type": "tags",
                "width": 220,
                "placeholder": "Search Wallhaven tags…",
                "options": [
                    {"label": "Any tag", "value": ""},
                    {"label": "Nature", "value": "nature"},
                    {"label": "Landscape", "value": "landscape"},
                    {"label": "Anime", "value": "anime"},
                    {"label": "City", "value": "city"},
                    {"label": "Space", "value": "space"},
                    {"label": "Minimalism", "value": "minimalism"},
                    {"label": "Fantasy", "value": "fantasy"},
                    {"label": "Abstract", "value": "abstract"},
                    {"label": "Architecture", "value": "architecture"},
                    {"label": "Mountains", "value": "mountains"},
                    {"label": "Ocean", "value": "ocean"},
                    {"label": "Forest", "value": "forest"},
                    {"label": "Sunset", "value": "sunset"},
                    {"label": "Cyberpunk", "value": "cyberpunk"},
                    {"label": "Cars", "value": "cars"},
                    {"label": "Video games", "value": "video games"},
                    {"label": "Animals", "value": "animals"},
                    {"label": "Flowers", "value": "flowers"},
                    {"label": "Night", "value": "night"},
                    {"label": "Beach", "value": "beach"},
                    {"label": "Rain", "value": "rain"},
                    {"label": "Water", "value": "water"},
                    {"label": "Clouds", "value": "clouds"},
                    {"label": "Dark", "value": "dark"},
                    {"label": "Music", "value": "music"},
                ],
            },
            {
                "key": "sorting",
                "label": "Sort",
                "width": 142,
                "options": [
                    {"label": "Toplist", "value": "toplist"},
                    {"label": "Date added", "value": "date_added"},
                    {"label": "Most viewed", "value": "views"},
                    {"label": "Most favorited", "value": "favorites"},
                    {"label": "Hot", "value": "hot"},
                    {"label": "Relevance", "value": "relevance"},
                ],
            },
            {
                "key": "topRange",
                "label": "Toplist period",
                "width": 118,
                "when": {"key": "sorting", "value": "toplist"},
                "options": [
                    {"label": "1 day", "value": "1d"},
                    {"label": "3 days", "value": "3d"},
                    {"label": "1 week", "value": "1w"},
                    {"label": "1 month", "value": "1M"},
                    {"label": "3 months", "value": "3M"},
                    {"label": "6 months", "value": "6M"},
                    {"label": "1 year", "value": "1y"},
                ],
            },
            {
                "key": "ratio",
                "label": "Aspect ratio",
                "width": 135,
                "options": [
                    {"label": "Any ratio", "value": ""},
                    {"label": "16:9", "value": "16x9"},
                    {"label": "16:10", "value": "16x10"},
                    {"label": "21:9", "value": "21x9"},
                    {"label": "32:9", "value": "32x9"},
                    {"label": "9:16", "value": "9x16"},
                    {"label": "10:16", "value": "10x16"},
                    {"label": "1:1", "value": "1x1"},
                    {"label": "3:2", "value": "3x2"},
                    {"label": "4:3", "value": "4x3"},
                    {"label": "5:4", "value": "5x4"},
                ],
            },
            {
                "key": "resolution",
                "label": "Minimum resolution",
                "width": 152,
                "options": [
                    {"label": "Any resolution", "value": ""},
                    {"label": "1920 × 1080+", "value": "1920x1080"},
                    {"label": "2560 × 1440+", "value": "2560x1440"},
                    {"label": "3840 × 2160+", "value": "3840x2160"},
                ],
            },
        ],
    },
    "bing": {
        "id": "bing",
        "name": "Bing Daily",
        "random": True,
        "search": True,
        "defaultFilters": {"country": "US"},
        "filters": [
            {
                "key": "country",
                "label": "Country",
                "width": 170,
                "options": [
                    {"label": "United States", "value": "US"},
                    {"label": "United Kingdom", "value": "GB"},
                    {"label": "Canada", "value": "CA"},
                    {"label": "Australia", "value": "AU"},
                    {"label": "India", "value": "IN"},
                    {"label": "Vietnam", "value": "VN"},
                    {"label": "Germany", "value": "DE"},
                    {"label": "France", "value": "FR"},
                    {"label": "Spain", "value": "ES"},
                    {"label": "Italy", "value": "IT"},
                    {"label": "Japan", "value": "JP"},
                    {"label": "Brazil", "value": "BR"},
                    {"label": "Mexico", "value": "MX"},
                ],
            }
        ],
    },
}


PROVIDERS["wallpaper_engine"] = wallpaper_engine.PROVIDER


def config_root():
    value = os.environ.get("XDG_CONFIG_HOME", "")
    path = Path(value).expanduser() if value else Path.home() / ".config"
    return path if path.is_absolute() else Path.home() / ".config"


def data_root():
    value = os.environ.get("XDG_DATA_HOME", "")
    path = Path(value).expanduser() if value else Path.home() / ".local" / "share"
    return path if path.is_absolute() else Path.home() / ".local" / "share"


def cache_root():
    value = Path(os.environ.get("XDG_CACHE_HOME", "~/.local/cache")).expanduser()
    return value if value.is_absolute() else Path.home() / ".local/cache"


def favorite_file():
    return data_root() / "quickshell/desktop/spaces/pictures" / "favorites.json"


def allowed_remote_url(value, hosts):
    parsed = urlparse(str(value or ""))
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username
        or parsed.password
    ):
        return ""
    return parsed.geturl()


def clean_wallhaven_item(raw):
    if not isinstance(raw, dict):
        return None
    wallpaper_id = str(raw.get("id", ""))
    if not WALLHAVEN_ID.fullmatch(wallpaper_id):
        return None
    page = allowed_remote_url(raw.get("url"), {"wallhaven.cc", "www.wallhaven.cc"})
    path = allowed_remote_url(raw.get("path"), {"w.wallhaven.cc"})
    thumbs = raw.get("thumbs") if isinstance(raw.get("thumbs"), dict) else {}
    small = allowed_remote_url(raw.get("thumbSmall") or thumbs.get("small"), {"th.wallhaven.cc"})
    large = allowed_remote_url(raw.get("thumbLarge") or thumbs.get("large"), {"th.wallhaven.cc"})
    preview = (
        allowed_remote_url(raw.get("preview") or thumbs.get("original"), {"th.wallhaven.cc"})
        or large
    )
    if not path:
        return None
    try:
        width = max(0, int(raw.get("dimension_x", raw.get("width", 0))))
        height = max(0, int(raw.get("dimension_y", raw.get("height", 0))))
        size = max(0, int(raw.get("file_size", raw.get("fileSize", 0))))
        views = max(0, int(raw.get("views", 0)))
        favorites = max(0, int(raw.get("favorites", 0)))
    except (TypeError, ValueError):
        width = height = size = views = favorites = 0
    category = str(raw.get("category") or "")
    purity = str(raw.get("purity") or "sfw")
    created_at = str(raw.get("created_at") or raw.get("createdAt") or "")
    category_label = {"100": "General", "010": "Anime", "001": "People"}.get(
        category, category.title()
    )
    purity_label = {
        "100": "SFW",
        "110": "SFW + Sketchy",
        "111": "SFW + Sketchy + NSFW",
        "sfw": "SFW",
        "sketchy": "Sketchy",
        "nsfw": "NSFW",
    }.get(purity.lower(), purity)
    raw_tags = raw.get("tags", [])
    tags = []
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            name = tag.get("name", "") if isinstance(tag, dict) else tag
            name = str(name or "").strip()
            if name and name not in tags:
                tags.append(name[:80])
            if len(tags) >= 40:
                break
    metadata = []
    if category:
        metadata.append({"label": "Category", "value": category_label})
    if purity:
        metadata.append({"label": "Rating", "value": purity_label})
    if created_at:
        metadata.append({"label": "Added", "value": created_at})
    if views:
        metadata.append({"label": "Views", "value": f"{views:,}"})
    if favorites:
        metadata.append({"label": "Favorites", "value": f"{favorites:,}"})
    if tags:
        metadata.append({"label": "Tags", "value": ", ".join(tags[:12])})
    return {
        "provider": "wallhaven",
        "providerName": "Wallhaven",
        "siteName": "Wallhaven",
        "id": wallpaper_id,
        "title": "",
        "url": page or f"https://wallhaven.cc/w/{wallpaper_id}",
        "path": path,
        "thumbSmall": small or preview,
        "thumbLarge": large or preview,
        "preview": preview,
        "width": width,
        "height": height,
        "resolution": str(
            raw.get("resolution")
            or (f"{width}x{height}" if width and height else "Unknown resolution")
        ),
        "fileSize": size,
        "fileType": str(raw.get("file_type") or raw.get("fileType") or "image/unknown"),
        "category": category,
        "purity": purity,
        "views": views,
        "favorites": favorites,
        "createdAt": created_at,
        "colors": [
            color
            for color in raw.get("colors", [])[:8]
            if isinstance(color, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", color)
        ]
        if isinstance(raw.get("colors"), list)
        else [],
        "tags": tags,
        "metadata": metadata,
        "attribution": "",
    }


def clean_bing_item(raw):
    if not isinstance(raw, dict):
        return None
    market = str(raw.get("market") or "en-US")
    if market not in BING_MARKETS.values():
        market = "en-US"
    country = market[-2:]
    date = str(raw.get("date") or raw.get("startdate") or "")
    if not re.fullmatch(r"\d{8}", date):
        return None
    wallpaper_id = str(raw.get("id") or f"{date}-{market}")
    if not re.fullmatch(r"\d{8}-[a-z]{2}-[A-Z]{2}", wallpaper_id):
        return None
    path = allowed_remote_url(raw.get("path"), {"www.bing.com", "bing.com"})
    if not path:
        return None
    page = (
        allowed_remote_url(raw.get("url"), {"www.bing.com", "bing.com"}) or "https://www.bing.com/"
    )
    try:
        width = max(0, int(raw.get("width", 1920)))
        height = max(0, int(raw.get("height", 1080)))
    except (TypeError, ValueError):
        width, height = 1920, 1080
    title = str(raw.get("title") or "Bing daily image")[:240]
    attribution = str(raw.get("attribution") or raw.get("copyright") or "")[:600]
    published = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    return {
        "provider": "bing",
        "providerName": "Bing Daily",
        "siteName": "Bing",
        "id": wallpaper_id,
        "date": date,
        "market": market,
        "title": title,
        "url": page,
        "path": path,
        "thumbSmall": path,
        "thumbLarge": path,
        "preview": path,
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}" if width and height else "Unknown resolution",
        "fileSize": 0,
        "fileType": "image/jpeg",
        "category": "",
        "purity": "",
        "views": 0,
        "favorites": 0,
        "createdAt": published,
        "colors": [],
        "metadata": [
            {"label": "Country", "value": country},
            {"label": "Published", "value": published},
        ],
        "attribution": attribution,
    }


def clean_item(raw, include_disabled=False):
    if not isinstance(raw, dict):
        return None
    provider = str(raw.get("provider") or "wallhaven")
    if provider == "wallpaper_engine":
        return wallpaper_engine.clean_item(raw)
    if provider == "bing":
        return clean_bing_item(raw)
    if provider == "wallhaven":
        return clean_wallhaven_item(raw)
    return command_providers.clean_item(raw, include_disabled=include_disabled)


def api_error_message(error, provider="Wallhaven"):
    try:
        data = json.loads(error.read().decode("utf-8", "replace"))
        errors = data.get("error", data.get("errors", ""))
        if isinstance(errors, list):
            errors = " ".join(str(value) for value in errors)
        if isinstance(errors, dict):
            errors = " ".join(str(value) for value in errors.values())
        return str(errors or f"{provider} returned HTTP {error.code}.")
    except Exception:
        return f"{provider} returned HTTP {error.code}."


def api_request(endpoint, params):
    url = API_ROOT + "/" + endpoint + "?" + urlencode(params)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read(12 * 1024 * 1024 + 1).decode("utf-8"))
    except HTTPError as error:
        raise ValueError(api_error_message(error)) from error
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError(f"Could not reach Wallhaven: {error}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Wallhaven returned an unreadable response.") from error
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise ValueError("Wallhaven returned an unexpected response.")
    return result


class WallhavenTagParser(HTMLParser):
    """Read tag names from Wallhaven's public HTML tag search page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.taglist_depth = 0
        self.name_depth = 0
        self.current = None
        self.tags = []
        self.seen = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div":
            if self.taglist_depth:
                self.taglist_depth += 1
            elif attributes.get("id") == "taglist":
                self.taglist_depth = 1
        elif self.taglist_depth and tag == "span" and "taglist-name" in classes:
            self.name_depth += 1
        elif self.name_depth and tag == "a":
            match = re.fullmatch(r"/tag/(\d+)", urlparse(attributes.get("href", "")).path)
            if match:
                self.current = {
                    "id": match.group(1),
                    "name": str(attributes.get("title") or "").strip(),
                    "text": [],
                }

    def handle_data(self, data):
        if self.current is not None:
            text = self.current["text"]
            assert isinstance(text, list)
            text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            name = self.current["name"] or " ".join("".join(self.current["text"]).split())
            tag_id = self.current["id"]
            if name and tag_id not in self.seen:
                self.tags.append({"id": tag_id, "name": name[:120]})
                self.seen.add(tag_id)
            self.current = None
        elif tag == "span" and self.name_depth:
            self.name_depth -= 1
        elif tag == "div" and self.taglist_depth:
            self.taglist_depth -= 1


def search_wallhaven_tags(args):
    query = str(args.get("query", "")).strip()[:100]
    if not query:
        return {"query": "", "tags": []}

    cache_key = query.casefold()
    cached = WALLHAVEN_TAG_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < 300:
        return {"query": query, "tags": cached[1]}

    url = "https://wallhaven.cc/tag/search?" + urlencode({"q": query})
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urlopen(request, timeout=10) as response:
            page = response.read(2 * 1024 * 1024 + 1).decode("utf-8", "replace")
        page = page[: 2 * 1024 * 1024]
    except (HTTPError, URLError, TimeoutError, OSError):
        return {"query": query, "tags": []}

    parser = WallhavenTagParser()
    parser.feed(page)
    tags = parser.tags[:20]
    if len(WALLHAVEN_TAG_CACHE) >= 100:
        oldest = min(WALLHAVEN_TAG_CACHE, key=lambda key: WALLHAVEN_TAG_CACHE[key][0])
        del WALLHAVEN_TAG_CACHE[oldest]
    WALLHAVEN_TAG_CACHE[cache_key] = (time.time(), tags)
    return {"query": query, "tags": tags}


def search_parameters(args, random_order=False):
    filters = args.get("filters") if isinstance(args.get("filters"), dict) else {}
    categories = str(filters.get("categories", "111"))
    purity = str(filters.get("purity", "100"))
    sorting = "random" if random_order else str(filters.get("sorting", "toplist"))
    if categories not in ALLOWED_CATEGORIES:
        categories = "111"
    if purity not in ALLOWED_PURITY:
        purity = "100"
    if sorting not in ALLOWED_SORTING:
        sorting = "toplist"
    params = {"categories": categories, "purity": purity, "sorting": sorting, "order": "desc"}
    if sorting == "toplist":
        top_range = str(filters.get("topRange", "1M"))
        params["topRange"] = top_range if top_range in ALLOWED_RANGES else "1M"
    ratio = str(filters.get("ratio", ""))
    if ratio in ALLOWED_RATIOS:
        params["ratios"] = ratio
    resolution = str(filters.get("resolution", ""))
    if resolution in ALLOWED_RESOLUTIONS and resolution:
        params["atleast"] = resolution
    query = str(args.get("query", "")).strip()[:180]
    tag_query = str(filters.get("tagQuery", "")).strip()[:200]
    if query and re.fullmatch(r"id:\d+", tag_query, re.IGNORECASE):
        tag_name = str(filters.get("tagLabel", "")).strip()
        if tag_name and not tag_name.lower().startswith("id:"):
            escaped_name = tag_name.replace("\\", "\\\\").replace('"', '\\"')
            tag_query = '+"' + escaped_name + '"'
        else:
            query = ""
    query = " ".join(part for part in (query, tag_query) if part)[:320]
    if query:
        params["q"] = query
    try:
        page = max(1, min(500, int(args.get("page", 1))))
    except (TypeError, ValueError):
        page = 1
    params["page"] = str(page)
    return params


def selected_provider(args):
    provider = str(args.get("provider") or "wallhaven").strip().lower()
    if provider not in PROVIDERS and provider not in command_providers.configured():
        raise ValueError(f"Unknown wallpaper provider: {provider}")
    return provider


def item_search_text(item):
    metadata = item.get("metadata", [])
    metadata_text = (
        " ".join(str(part.get("value", "")) for part in metadata if isinstance(part, dict))
        if isinstance(metadata, list)
        else ""
    )
    return (
        " ".join(
            str(item.get(key, ""))
            for key in (
                "id",
                "title",
                "providerName",
                "category",
                "purity",
                "resolution",
                "attribution",
                "description",
            )
        )
        + " "
        + metadata_text
    )


def browse_favorites(args):
    query = str(args.get("query", "")).strip().casefold()
    items = load_favorites()
    if query:
        items = [item for item in items if query in item_search_text(item).casefold()]
    return {"items": items, "next": 0, "total": len(items)}


def browse_wallhaven(args):
    data = api_request("search", search_parameters(args))
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    try:
        current_page = int(meta.get("current_page", args.get("page", 1)))
        last_page = int(meta.get("last_page", current_page))
    except (TypeError, ValueError):
        current_page = last_page = 1
    items = [item for value in data["data"] if (item := clean_wallhaven_item(value))]
    return {
        "items": items,
        "next": current_page + 1 if current_page < last_page else 0,
        "total": max(0, int(meta.get("total", 0) or 0)),
    }


def bing_market(args):
    filters = args.get("filters") if isinstance(args.get("filters"), dict) else {}
    country = str(filters.get("country", args.get("country", "US"))).upper()
    return BING_MARKETS.get(country, BING_MARKETS["US"])


def bing_feed(market, index):
    params = {"format": "js", "idx": str(max(0, min(8, int(index)))), "n": "8", "mkt": market}
    url = BING_FEED_ROOT + "?" + urlencode(params)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read(3 * 1024 * 1024 + 1).decode("utf-8"))
    except HTTPError as error:
        raise ValueError(api_error_message(error, "Bing")) from error
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError(f"Could not reach Bing: {error}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Bing returned an unreadable image feed.") from error
    if not isinstance(data, dict) or not isinstance(data.get("images"), list):
        raise ValueError("Bing returned an unexpected image feed.")
    result = []
    for record in data["images"]:
        if not isinstance(record, dict):
            continue
        raw_path = str(record.get("url") or "")
        image_url = "https://www.bing.com" + raw_path if raw_path.startswith("/") else raw_path
        copyright_url = str(record.get("copyrightlink") or "")
        item = clean_bing_item(
            {
                "provider": "bing",
                "id": f"{record.get('startdate', '')}-{market}",
                "date": record.get("startdate", ""),
                "market": market,
                "title": record.get("title", ""),
                "path": image_url,
                "url": copyright_url,
                "attribution": record.get("copyright", ""),
                "width": 1920,
                "height": 1080,
            }
        )
        if item:
            result.append(item)
    return result


def browse_bing(args):
    market = bing_market(args)
    cached_at, cached_items = BING_CATALOG_CACHE.get(market, (0, None))
    if cached_items is None or time.monotonic() - cached_at >= BING_CACHE_SECONDS:
        items = bing_feed(market, 0)
        # Bing's public feed caps each response at eight items. Its second
        # window overlaps by one day and is currently the oldest window exposed.
        items.extend(bing_feed(market, 8))
        unique = []
        seen = set()
        for item in items:
            if item["id"] not in seen:
                seen.add(item["id"])
                unique.append(item)
        BING_CATALOG_CACHE[market] = (time.monotonic(), unique)
    else:
        unique = cached_items
    query = str(args.get("query", "")).strip().casefold()
    if query:
        unique = [item for item in unique if query in item_search_text(item).casefold()]
    return {"items": unique, "next": 0, "total": len(unique)}


BROWSE_HANDLERS = {
    "wallhaven": browse_wallhaven,
    "bing": browse_bing,
    "wallpaper_engine": wallpaper_engine.browse,
}


def browse(args):
    if args.get("favorites"):
        return browse_favorites(args)
    provider = selected_provider(args)
    if provider not in PROVIDERS:
        return command_providers.browse(dict(args, provider=provider))
    handler = BROWSE_HANDLERS.get(provider)
    if not handler:
        raise ValueError(f"{PROVIDERS[provider]['name']} does not support browsing.")
    return handler(args)


def random_wallhaven(args):
    data = api_request("search", search_parameters(args, random_order=True))
    items = [item for value in data["data"] if (item := clean_item(value))]
    if not items:
        raise ValueError("No wallpapers matched these filters.")
    # Wallhaven returns results in random order; use its first result directly.
    return items[0]


def random_bing(args):
    items = browse_bing(args)["items"]
    if not items:
        raise ValueError("Bing has no recent images for this country.")
    return random.choice(items)


RANDOM_HANDLERS = {"wallhaven": random_wallhaven, "bing": random_bing}


def random_wallpaper(args):
    provider = selected_provider(args)
    if provider not in PROVIDERS:
        raise ValueError("This wallpaper provider does not support random selection.")
    if not PROVIDERS[provider].get("random"):
        raise ValueError(f"{PROVIDERS[provider]['name']} does not support random selection.")
    handler = RANDOM_HANDLERS.get(provider)
    if not handler:
        raise ValueError(f"No random selection is implemented for {PROVIDERS[provider]['name']}.")
    return handler(args)


def provider_catalog():
    return {
        "providers": [
            wallpaper_engine.descriptor() if value["id"] == "wallpaper_engine" else value
            for value in PROVIDERS.values()
        ]
        + command_providers.descriptors(),
        "currentProvider": current_wallpaper_provider(),
    }


def current_wallpaper_provider():
    setting = wallpaper_engine.read_setting()
    if setting.get("mode") == "wallpaper_engine":
        return "wallpaper_engine"
    if (
        setting.get("provider") in PROVIDERS
        or setting.get("provider") in command_providers.configured()
    ):
        return setting["provider"]
    return "wallhaven"


def load_favorites(include_disabled=False):
    path = favorite_file()
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, list):
            return []
        items = [
            item for raw in values if (item := clean_item(raw, include_disabled=include_disabled))
        ]
        return items[:2000]
    except (OSError, json.JSONDecodeError):
        return []


def save_favorites(args):
    item = clean_item(args.get("wallpaper"))
    if not item:
        raise ValueError("Select a valid wallpaper first.")
    favorites = load_favorites(include_disabled=True)
    is_favorite = bool(args.get("favorite"))
    key = (item["provider"], item["id"])
    favorites = [value for value in favorites if (value["provider"], value["id"]) != key]
    if is_favorite:
        favorites.insert(0, item)
    path = favorite_file()
    atomic_write(path, json.dumps(favorites[:2000], ensure_ascii=False, indent=2) + "\n")
    return {
        "favorite": is_favorite,
        "count": len(favorites) if is_favorite else max(0, len(favorites)),
    }


def wallpaper_file(item):
    suffix = Path(urlparse(item["path"]).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        suffix = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/avif": ".avif",
        }.get(item["fileType"].lower(), ".jpg")
    folder = cache_root() / "quickshell/desktop/spaces/pictures" / "wallpapers"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", item["id"])
    if item["provider"] not in PROVIDERS:
        safe_id = command_providers.cache_id(item)
    if item.get("kind") == "video":
        suffix = ".mp4"
    return folder / (item["provider"] + "-" + safe_id + suffix)


def download_wallpaper(item):
    path = wallpaper_file(item)
    if path.is_file() and path.stat().st_size:
        return path
    url, headers = (
        command_providers.resolve(item) if item["provider"] not in PROVIDERS else (item["path"], {})
    )
    video = item.get("kind") == "video"
    maximum = 1024 * 1024 * 1024 if video else MAX_IMAGE_BYTES
    request = Request(
        url,
        headers={"Accept": "video/*" if video else "image/*", "User-Agent": USER_AGENT, **headers},
    )
    temporary = None
    deadline = time.monotonic() + WALLPAPER_DOWNLOAD_SECONDS
    try:
        with urlopen(request, timeout=10) as response:
            content_type = response.headers.get_content_type()
            if not content_type.startswith("video/" if video else "image/") and not (
                video and content_type == "application/octet-stream"
            ):
                raise ValueError(f"{item['providerName']} did not return a wallpaper file.")
            length = response.headers.get("Content-Length")
            if length and int(length) > maximum:
                raise ValueError("This wallpaper is too large to download.")
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=f".pictures-{os.getpid()}-",
                suffix=".download",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                total = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise ValueError("Wallpaper download timed out. Try again.")
                    # read1 returns available data instead of waiting for a full
                    # megabyte from a slow server before checking the deadline.
                    chunk = response.read1(256 * 1024)
                    if time.monotonic() >= deadline:
                        raise ValueError("Wallpaper download timed out. Try again.")
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > maximum:
                        raise ValueError("This wallpaper is too large to download.")
                    output.write(chunk)
        if total == 0:
            raise ValueError(f"{item['providerName']} returned an empty image file.")
        if video:
            with temporary.open("rb") as saved:
                header = saved.read(12)
            if len(header) < 12 or header[4:8] != b"ftyp":
                raise ValueError("Wallpaper provider did not return an MP4 video.")
        os.replace(temporary, path)
        return path
    except HTTPError as error:
        raise ValueError(api_error_message(error, item["providerName"])) from error
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError("Could not download this wallpaper. Retry later.") from error
    finally:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)


def apply_shell_wallpaper(path, provider=None):
    from spaces.pictures.wallpaper import current_image

    setting = config_root() / "quickshell/desktop/spaces/pictures/wallpaper.json"
    still = current_image()
    previous = still.read_bytes() if still.is_file() else None
    value = {"image": still.as_uri()}
    if provider in PROVIDERS or provider in command_providers.configured():
        value["provider"] = provider
    apply_lock_wallpaper(path)
    try:
        atomic_write(setting, json.dumps(value) + "\n")
    except OSError:
        if previous is None:
            still.unlink(missing_ok=True)
        else:
            atomic_write(still, previous)
        raise
    return "desktop shell"


def apply_lock_wallpaper(path):
    from spaces.pictures.wallpaper import update_lock_background

    update_lock_background(path, config_root())


def set_wallpaper(args):
    item = clean_item(args.get("wallpaper"))
    if not item:
        raise ValueError("Select a valid wallpaper first.")
    target = args.get("target", "shell")
    if target != "shell":
        raise ValueError("Unknown wallpaper target.")
    if item["provider"] == "wallpaper_engine":
        if target != "shell":
            raise ValueError("Use Wallpaper Engine from the desktop shell.")
        return wallpaper_engine.apply(item)
    if item.get("kind") == "video":
        if target != "shell":
            raise ValueError("Use video wallpapers from the desktop shell.")
        video_wallpaper.requirements()
        path = download_wallpaper(item)
        return video_wallpaper.apply(path, item["provider"])
    path = download_wallpaper(item)
    if target == "shell":
        with wallpaper_engine.control_lock():
            animated = wallpaper_engine.read_setting().get("mode") in {"wallpaper_engine", "video"}
            service = apply_shell_wallpaper(path, item["provider"])
        if animated:
            wallpaper_engine.wait_idle()
    return {
        "path": str(path),
        "service": service,
        "message": "Wallpaper set using " + service + ". Lock screen updated.",
    }


def preferences(values=None):
    path = config_root() / "quickshell/desktop/spaces/pictures/pictures-ui.json"
    if values is not None:
        if (not isinstance(values, dict) or values.keys() - {"grid", "provider", "filters"}
                or type(values.get("grid")) is not bool
                or not isinstance(values.get("provider"), str)
                or not isinstance(values.get("filters"), dict)
                or len(json.dumps(values)) > 64000):
            raise ValueError("Invalid Pictures preferences.")
        atomic_write(path, json.dumps(values) + "\n")
        return values
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError("Could not read Pictures preferences.") from None


def run(request):
    op = request.get("op")
    if op == "preferences":
        return preferences()
    if op == "savePreferences":
        return preferences(request.get("values"))
    if op == "providers":
        return provider_catalog()
    if op == "tagSearch":
        return search_wallhaven_tags(request)
    if op == "browse":
        return browse(request)
    if op == "random":
        return {"wallpaper": random_wallpaper(request)}
    if op == "favorite":
        return save_favorites(request)
    if op == "randomSet":
        item = random_wallpaper({"provider": "wallhaven", "filters": {"purity": "100"}})
        return set_wallpaper({"wallpaper": item})
    if op == "set":
        return set_wallpaper(request)
    if op == "openWorkshop":
        return wallpaper_engine.open_workshop(request)
    if op == "installationStatus":
        item = clean_item(request.get("wallpaper"))
        if not item or item["provider"] != "wallpaper_engine":
            raise ValueError("Invalid Wallpaper Engine wallpaper.")
        return wallpaper_engine.installation_status(item)
    raise ValueError("Unsupported Pictures service request.")


def command_line():
    parser = argparse.ArgumentParser(description="Set a random wallpaper from Pictures providers.")
    parser.add_argument(
        "--random", action="store_true", help="download and apply a random wallpaper"
    )
    parser.add_argument(
        "--target",
        choices=("shell",),
        default="shell",
        help="apply to the desktop shell (default) to every display",
    )
    parser.add_argument(
        "--provider",
        choices=tuple(PROVIDERS),
        help="choose a provider; default: choose one at random",
    )
    parser.add_argument(
        "--country",
        choices=tuple(BING_MARKETS),
        default="US",
        help="Bing market country (default: US)",
    )
    args = parser.parse_args()
    if not args.random:
        parser.error("use --random to apply a random wallpaper")
    try:
        random_providers = [name for name, value in PROVIDERS.items() if value.get("random")]
        provider = args.provider or random.choice(random_providers)
        request = {"provider": provider}
        if provider == "wallhaven":
            request["filters"] = {"categories": "111", "purity": "100", "sorting": "random"}
        else:
            request["filters"] = {"country": args.country}
        item = random_wallpaper(request)
        result = set_wallpaper({"wallpaper": item, "target": args.target})
        print(
            f"Set {item['providerName']} wallpaper {item['id']} using {result['service']}: {result['path']}"
        )
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


def worker():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from spaces.movies.worker import serve

    def cleanup():
        folder = cache_root() / "quickshell/desktop/spaces/pictures/wallpapers"
        for path in folder.glob(f".pictures-{os.getpid()}-*.download"):
            path.unlink(missing_ok=True)

    command_providers.install_shutdown_handler(cleanup)
    try:
        serve(
            run,
            latest=("browse", "tagSearch", "installationStatus"),
            controls=("favorite", "set", "randomSet", "openWorkshop", "savePreferences"),
            scope=lambda r: (r["op"], bool(r.get("favorites"))),
        )
    finally:
        command_providers.runner.close()
        cleanup()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(command_line())
    worker()
