"""Read-only Steam Workshop discovery. No Steam or renderer process is started."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

APP_ID = 431960
SORTS = {"popular": 0, "newest": 1, "trending": 3, "relevance": 12}
TAGS = [
    "Anime",
    "Abstract",
    "Animal",
    "Cars",
    "Fantasy",
    "Game",
    "Landscape",
    "Nature",
    "Relaxing",
    "Science Fiction",
    "Space",
    "Technology",
]


def api_key(folder):
    # Share the existing credential, without importing or starting Games.
    for path, nested in ((folder / "pictures.json", True), (folder.parent / "games/games.json", False)):
        try:
            config = json.loads(path.read_text())
            if nested:
                config = config.get("wallpaper_engine", {})
            value = config.get("steam_api_key", "")
            if isinstance(value, str) and value.strip():
                return value.strip()
        except (OSError, ValueError, AttributeError):
            continue
    return ""


def preview_url(value):
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlparse(value)
        host = parsed.hostname or ""
        allowed = any(
            host == domain or host.endswith("." + domain)
            for domain in ("steamusercontent.com", "steamuserimages-a.akamaihd.net")
        )
        if (
            parsed.scheme == "https"
            and allowed
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
        ):
            return value[:4000]
    except ValueError:
        pass
    return ""


def original_preview(value):
    value = preview_url(value)
    if not value:
        return ""
    parsed = urlparse(value)
    resizing = {"imw", "imh", "ima", "impolicy", "imcolor", "letterbox"}
    query = [(key, val) for key, val in parse_qsl(parsed.query) if key.lower() not in resizing]
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


def thumbnail(value):
    value = original_preview(value)
    if not value:
        return ""
    parsed = urlparse(value)
    query = parse_qsl(parsed.query) + [
        ("imw", "400"),
        ("imh", "400"),
        ("ima", "fit"),
        ("impolicy", "Letterbox"),
        ("letterbox", "false"),
    ]
    return urlunparse(parsed._replace(query=urlencode(query)))


def full_preview(row):
    # Primary previews are often tiny GIFs. Additional image previews are
    # creator-uploaded stills; do not substitute video IDs or invent assets.
    previews = row.get("previews", [])
    if isinstance(previews, list):
        for entry in previews[:100]:
            if isinstance(entry, dict) and entry.get("preview_type") == 0:
                image = original_preview(entry.get("url"))
                if image:
                    return image
    return original_preview(row.get("preview_url"))


def query(folder, args):
    key = api_key(folder)
    if not key:
        raise ValueError(
            "Workshop search needs steam_api_key in games.json or wallpaper_engine.steam_api_key in pictures.json."
        )
    filters = args.get("filters") if isinstance(args.get("filters"), dict) else {}
    required_tags = ["Everyone"]
    kind = str(filters.get("type") or "").lower()
    if kind in {"scene", "video", "web"}:
        required_tags.append(kind.capitalize())
    tag = str(filters.get("workshopTag") or "")
    if tag in TAGS:
        required_tags.append(tag)
    page = args.get("page")
    cursor = page if isinstance(page, str) and len(page) <= 2048 else "*"
    parameters = {
        "appid": APP_ID,
        "query_type": SORTS.get(filters.get("workshopSort"), 0),
        "cursor": cursor,
        "numperpage": 30,
        "search_text": str(args.get("query") or "")[:200],
        "requiredtags": required_tags,
        "match_all_tags": True,
        "days": 7,
        "return_tags": True,
        "return_short_description": True,
        "return_previews": True,
    }
    url = "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/?" + urlencode(
        {"key": key, "input_json": json.dumps(parameters)}
    )
    request = Request(
        url, headers={"Accept": "application/json", "User-Agent": "Desktop-Pictures/1.0"}
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Steam Workshop response was too large.")
        data = json.loads(raw).get("response", {})
    except HTTPError as error:
        # Never include the authenticated URL, key, or raw upstream body.
        message = (
            "Steam rejected the API key."
            if error.code in {401, 403}
            else "Steam Workshop search failed. Try again later."
        )
        error.close()
        raise ValueError(message) from None
    except (URLError, OSError, TimeoutError):
        raise ValueError("Could not reach Steam Workshop. Try again.") from None
    except (ValueError, AttributeError):
        raise ValueError("Steam returned an unreadable Workshop catalogue.") from None
    if not isinstance(data, dict) or not isinstance(data.get("publishedfiledetails", []), list):
        raise ValueError("Steam returned an unexpected Workshop catalogue.")
    if data.get("result", 1) != 1:
        raise ValueError("Steam Workshop search failed. Check your Steam API key.")
    rows = data.get("publishedfiledetails", [])[:30]
    next_cursor = data.get("next_cursor")
    if (
        not isinstance(next_cursor, str)
        or len(next_cursor) > 2048
        or next_cursor == cursor
        or not rows
    ):
        next_cursor = 0
    return rows, next_cursor, data.get("total", 0)
