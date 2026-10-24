"""Config-driven anime playback adapters. Source endpoints stay in media.json."""

import base64
import difflib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request


class SourceError(Exception):
    pass


def _url(template, values):
    if not isinstance(template, str) or not template:
        raise SourceError("This anime source is incomplete in media.json.")
    try:
        url = re.sub(
            r"\{([a-zA-Z][a-zA-Z0-9]*)\}",
            lambda match: urllib.parse.quote(str(values[match[1]]), safe=""),
            template,
        )
    except KeyError:
        raise SourceError("This anime source has an unknown URL placeholder.") from None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SourceError("Anime source URLs must use HTTPS.")
    return url


def _get(url, referer=""):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=15
        ) as response:
            return response.read().decode("utf-8", "replace")
    except (OSError, urllib.error.HTTPError):
        raise SourceError("The selected anime source is unavailable. Try another source.") from None


def _get_field(url, field):
    body = _get(url)
    if not field:
        return body
    try:
        value = json.loads(body).get(field)
    except (ValueError, AttributeError):
        raise SourceError("This anime source returned an unreadable response.") from None
    if not isinstance(value, str):
        raise SourceError("This anime source returned no episode data.")
    return value


def _match(pattern, body, *, required=True):
    try:
        found = re.search(pattern, body, re.S)
    except (TypeError, re.error):
        raise SourceError("This anime source has an invalid pattern in media.json.") from None
    if not found and required:
        raise SourceError("This anime source has no matching stream for this title.")
    return found


def _normal(text):
    return re.sub(r"[^a-z0-9]", "", html.unescape(str(text)).lower())


def _choose_match(pattern, body, names):
    try:
        matches = list(re.finditer(pattern, body, re.S))
    except (TypeError, re.error):
        raise SourceError("This anime source has an invalid pattern in media.json.") from None
    wanted = {_normal(name) for name in names if name}
    wanted.discard("")
    ranked = []
    for match in matches:
        groups = match.groupdict()
        candidates = [_normal(groups.get(key, "")) for key in ("title", "alternate")]
        score = (
            max(
                (
                    1.0
                    if candidate in wanted
                    else max(
                        (difflib.SequenceMatcher(None, candidate, name).ratio() for name in wanted),
                        default=0,
                    )
                )
                for candidate in candidates
                if candidate
            )
            if any(candidates)
            else 0
        )
        ranked.append((score, groups))
    ranked.sort(key=lambda row: row[0], reverse=True)
    if (
        not ranked
        or ranked[0][0] < 0.86
        or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.05)
    ):
        raise SourceError("No confident match was found for this anime. Try another source.")
    return ranked[0][1]


def _stream_page(source, embed_url):
    body = _get(embed_url)
    blob = _match(source.get("blob_pattern"), body).group(1)
    key = source.get("xor_key", "").encode("utf-8")
    if not key:
        raise SourceError("This anime source is missing a decoder key in media.json.")
    try:
        raw = base64.b64decode(blob, validate=True)
        data = json.loads(bytes(value ^ key[index % len(key)] for index, value in enumerate(raw)))
    except (ValueError, UnicodeDecodeError):
        raise SourceError("The selected anime source returned an unreadable stream.") from None
    stream = data.get("src", "")
    if not isinstance(stream, str) or not stream.startswith("https://"):
        raise SourceError("This anime source has no playable stream for this episode.")
    subtitle = next(
        (
            track.get("src")
            for track in data.get("subtitles", [])
            if isinstance(track, dict)
            and track.get("default")
            and str(track.get("src", "")).startswith("https://")
        ),
        "",
    )
    parsed = urllib.parse.urlparse(embed_url)
    return {"url": stream, "referer": f"{parsed.scheme}://{parsed.netloc}/", "subtitle": subtitle}


def resolve(source, title, episode, mode):
    """Resolve a configured MAL-ID or title-search source to a playable stream."""
    mal_id = title.get("malId")
    if not str(mal_id).isdigit() or not str(episode).replace(".", "", 1).isdigit():
        raise SourceError("This anime needs a MAL ID and episode number for playback.")
    if mode not in ("sub", "dub"):
        raise SourceError("Choose sub or dub audio.")
    values = {"malId": mal_id, "episode": episode, "mode": mode, "title": title.get("title", "")}
    strategy = source.get("strategy")
    if strategy == "mal_embed":
        return _stream_page(source, _url(source.get("embed_url"), values))
    if strategy != "search_embed":
        raise SourceError("This anime source has an unsupported strategy in media.json.")

    search = _get(_url(source.get("search_url"), values))
    names = [title.get("title"), title.get("originalTitle"), *(title.get("aliases") or [])]
    match = _choose_match(source.get("result_pattern"), search, names)
    slug = match.get("slug", "")
    values["slug"] = slug
    values["siteId"] = slug.rsplit("-", 1)[-1]
    episodes = _get_field(_url(source.get("episodes_url"), values), source.get("episodes_field"))
    try:
        episode_matches = re.finditer(source.get("episode_pattern"), episodes, re.S)
        episode_id = next(
            (
                match.group("episodeId")
                for match in episode_matches
                if match.group("number") == str(episode)
            ),
            "",
        )
    except (TypeError, re.error, IndexError):
        raise SourceError("This anime source has an invalid episode pattern.") from None
    if not episode_id:
        raise SourceError("This anime source does not list the selected episode.")
    values["episodeId"] = episode_id
    servers = _get_field(_url(source.get("servers_url"), values), source.get("servers_field"))
    server = _match(source.get("server_pattern", "").replace("{mode}", re.escape(mode)), servers)
    try:
        embed = base64.b64decode(server.group(1), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise SourceError("This anime source returned an invalid player link.") from None
    return _stream_page(source, _url(embed, values))
