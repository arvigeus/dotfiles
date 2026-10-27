"""Bounded, anonymous reads of creators' public YouTube Posts and continuations."""
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
import time
from urllib.parse import urlsplit

import requests

from spaces.streaming.storage import StreamingError, atomic_json, read_json
from spaces.streaming.youtube import CHANNEL_ID, VIDEO_ID, channel_url, watch_url

POST_ID = re.compile(r"Ug[A-Za-z0-9_-]{10,100}\Z")


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def text(value, limit=8000):
    if isinstance(value, str):
        return value[:limit]
    if not isinstance(value, dict):
        return ""
    return str(value.get("simpleText") or "".join(str(r.get("text") or "") for r in value.get("runs", []) if isinstance(r, dict)))[:limit]


def image_url(value):
    if not isinstance(value, str) or len(value) > 4000:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        return value if (parsed.scheme == "https" and not parsed.username and not parsed.password and parsed.port in (None, 443)
                         and (host == "ytimg.com" or host.endswith(".ytimg.com") or host == "ggpht.com" or host.endswith(".ggpht.com")
                              or host == "yt3.googleusercontent.com")
                         and not any(ord(c) < 32 for c in value)) else ""
    except ValueError:
        return ""


def thumbnail(value):
    candidates = []
    for node in walk(value):
        if url := image_url(node.get("url")):
            width = node.get("width")
            candidates.append((width if isinstance(width, (float, int)) else 0, url))
    return max(candidates, default=(0, ""))[1]


def published_time(label, now=None):
    """Relative dates only support approximate ordering, never exact date display."""
    now = time.time() if now is None else now
    match = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s+ago", label.lower())
    if match:
        scale = dict(second=1, minute=60, hour=3600, day=86400, week=604800, month=2592000, year=31536000)
        return max(0, now - int(match[1]) * scale[match[2]])
    if label.lower().startswith("just now"):
        return now
    try:
        return datetime.strptime(label.split(" (edited)")[0], "%b %d, %Y").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0


def normalize(renderer, channel, now=None):
    identity = renderer.get("postId")
    if not isinstance(identity, str) or not POST_ID.fullmatch(identity):
        return None
    if "sponsorsOnlyBadge" in renderer or "membersOnlyBadge" in renderer or renderer.get("isMembersOnly"):
        return None
    for node in walk(renderer.get("badges", [])):
        if "MEMBERS_ONLY" in str(node.get("style", "")) or text(node.get("label")).casefold() in ("members only", "members-only"):
            return None
    author = renderer.get("authorEndpoint", {}).get("browseEndpoint", {})
    channel_id = author.get("browseId") or channel.get("id", "")
    channel_id = channel_id if isinstance(channel_id, str) and CHANNEL_ID.fullmatch(channel_id) else ""
    attachment = renderer.get("backstageAttachment") or {}
    images = []
    multi = attachment.get("postMultiImageRenderer", {}).get("images", [])
    singles = [attachment["backstageImageRenderer"]] if "backstageImageRenderer" in attachment else []
    for image in [*singles, *multi][:4]:
        if source := thumbnail(image):
            images.append(source)
    poll = attachment.get("pollRenderer") or {}
    options = [text(choice.get("text") or choice.get("optionText"), 1000) for choice in poll.get("choices", [])[:12] if isinstance(choice, dict)]
    videos = []
    for node in walk(attachment):
        for key in ("videoRenderer", "videoWithContextRenderer"):
            video = node.get(key)
            if isinstance(video, dict) and VIDEO_ID.fullmatch(str(video.get("videoId") or "")):
                videos.append(dict(id=video["videoId"], title=text(video.get("title"), 1000) or "Watch shared video", url=watch_url(video["videoId"])))
    date = text(renderer.get("publishedTimeText"), 100)
    return dict(id=identity, url="https://www.youtube.com/post/" + identity,
                creator=text(renderer.get("authorText"), 500) or channel.get("name", ""),
                channel=channel["url"], channelId=channel_id, followedChannelUrl=channel["url"],
                avatar=thumbnail(renderer.get("authorThumbnail", {})), text=text(renderer.get("contentText")),
                published=date, timestamp=published_time(date, now), likes=text(renderer.get("voteCount"), 100),
                images=images, poll=options, votes=text(poll.get("totalVotes"), 100),
                videos=list({v["id"]: v for v in videos}.values())[:4])


def script_json(html, pattern, required=""):
    for match in re.finditer(pattern, html):
        try:
            value, _ = json.JSONDecoder().raw_decode(html[match.end():])
            if isinstance(value, dict) and (not required or required in value):
                return value
        except ValueError:
            continue
    raise StreamingError("YouTube's Posts page could not be read. Try Refresh later.")


def selected_posts(data):
    for node in walk(data.get("contents", {})):
        tab = node.get("tabRenderer")
        if not isinstance(tab, dict) or not tab.get("selected"):
            continue
        endpoint = tab.get("endpoint", {}).get("commandMetadata", {}).get("webCommandMetadata", {}).get("url", "")
        if str(endpoint).split("?")[0].rstrip("/").endswith(("/posts", "/community")) or tab.get("title") == "Posts":
            return tab.get("content", {})
    return {}


def parse_page(data, channel, now=None):
    def feed_nodes(value):
        if isinstance(value, dict):
            yield value
            for key, child in value.items():
                if key not in ("backstagePostThreadRenderer", "postThreadRenderer"):
                    yield from feed_nodes(child)
        elif isinstance(value, list):
            for child in value:
                yield from feed_nodes(child)
    items, seen, token = [], set(), ""
    for node in feed_nodes(data):
        # Skip the post's nested replies: only the post field of each thread is read.
        thread = node.get("backstagePostThreadRenderer") or node.get("postThreadRenderer")
        if isinstance(thread, dict):
            content = thread.get("post", {})
            renderer = content.get("backstagePostRenderer") or content.get("postRenderer")
            if isinstance(renderer, dict) and (post := normalize(renderer, channel, now)) and post["id"] not in seen:
                seen.add(post["id"]); items.append(post)
        continuation = node.get("continuationItemRenderer")
        if isinstance(continuation, dict) and not token:
            for entry in walk(continuation):
                command = entry.get("continuationCommand")
                if isinstance(command, dict) and isinstance(command.get("token"), str):
                    token = command["token"][:20000]
                    break
    return items[:30], token


class PostsClient:
    def __init__(self, cache, fetch=None):
        self.cache = cache
        self.fetch = fetch or self.request
        self.lock = threading.Lock()
        self.channel_locks = {}

    @staticmethod
    def request(url, body=None, context=None):
        headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.8"}
        if body is not None:
            client = (context or {}).get("client", {})
            headers.update({"X-YouTube-Client-Name": "1", "X-YouTube-Client-Version": str(client.get("clientVersion") or ""), "Origin": "https://www.youtube.com"})
        try:
            with requests.request("GET" if body is None else "POST", url, json=body, headers=headers,
                                  timeout=(10, 25), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise StreamingError("YouTube Posts could not be loaded. Try Refresh later.")
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 12 * 1024 * 1024:
                        raise StreamingError("YouTube returned too much Posts data.")
                value = content.decode("utf-8", "replace")
                return value if body is None else json.loads(value)
        except (requests.RequestException, ValueError) as error:
            if isinstance(error, StreamingError):
                raise
            raise StreamingError("YouTube Posts could not be reached or returned unreadable data.") from None

    def page(self, channel, page):
        if type(page) is not int or not 0 <= page < 2**31:
            raise StreamingError("Refresh Posts to start a new feed.")
        url = channel_url(channel["url"])
        with self.lock:
            lock = self.channel_locks.setdefault(url, threading.RLock())
        with lock:
            path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".json")
            if not page:
                html = self.fetch(url + "/posts?hl=en")
                initial = script_json(html, r"(?:var\s+)?ytInitialData\s*=\s*")
                config = script_json(html, r"ytcfg\.set\(\s*", "INNERTUBE_CONTEXT")
                context = config.get("INNERTUBE_CONTEXT") or {}
                if not isinstance(context, dict) or len(json.dumps(context)) > 65536:
                    raise StreamingError("YouTube returned an invalid Posts context.")
                selected = selected_posts(initial)
                items, token = parse_page(selected, channel)
                state = dict(context=context, tokens={"1": token})
            else:
                state = read_json(path, {})
                if not isinstance(state.get("tokens"), dict):
                    self.page(channel, 0)
                    state = read_json(path, {})
                tokens = state["tokens"]
                if any(value == "" and int(key) <= page for key, value in tokens.items()):
                    return dict(items=[], more=False, pageKey="end")
                if str(page) not in tokens:
                    raise StreamingError("Refresh Posts before loading more.")
                token = tokens[str(page)]
                context = state.get("context") or {}
                data = self.fetch("https://www.youtube.com/youtubei/v1/browse?prettyPrint=false",
                                  dict(context=context, continuation=token), context)
                commands = data.get("onResponseReceivedActions") or data.get("onResponseReceivedEndpoints") or []
                items, token = parse_page(commands, channel)
                if token and any(value == token for key, value in tokens.items() if int(key) <= page):
                    token = ""
                if tokens.get(str(page + 1)) != token:
                    for key in list(tokens):
                        if int(key) > page:
                            del tokens[key]
                tokens[str(page + 1)] = token
                # Keep the initial cursor and a recent replay window, independently
                # of feed depth. Forward pagination does not need unbounded state.
                for old in sorted((key for key in tokens if key != "1"), key=int)[:-31]:
                    del tokens[old]
            atomic_json(path, state)
            with self.lock:
                files = sorted(self.cache.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
                for old in files[100:]:
                    old.unlink(missing_ok=True)
            key = hashlib.sha256(json.dumps([sorted(row["id"] for row in items), token]).encode()).hexdigest()
            return dict(items=items, more=bool(token), pageKey=key)
