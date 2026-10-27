"""Bounded yt-dlp commands; only canonical YouTube identities cross the UI boundary."""
import json
from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

from spaces.books.jobs import check_cancelled
from spaces.streaming.storage import StreamingError

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")


def access_error(availability):
    return {
        "subscriber_only": "This video is members-only. Open it on YouTube with an account that has channel membership.",
        "premium_only": "This video requires YouTube Premium. Open it on YouTube with an eligible account.",
        "private": "This video is private. Open it on YouTube with an account that has access.",
        "needs_auth": "This video requires YouTube sign-in. Open it on YouTube with an eligible account.",
    }.get(availability, "")


def command_error(diagnostic):
    """Classify provider failures without exposing raw URLs, tokens or stderr."""
    text = diagnostic.lower()
    if "members-only" in text or "join this channel" in text:
        return StreamingError(access_error("subscriber_only"), "members-only")
    if "private video" in text:
        return StreamingError(access_error("private"), "private")
    if "sign in" in text or "login required" in text or "age-restricted" in text:
        return StreamingError(access_error("needs_auth"), "sign-in")
    if "not available in your country" in text or "geo-restricted" in text:
        return StreamingError("This video is unavailable in your region.", "region")
    if "requested format is not available" in text:
        return StreamingError("This video has no compatible stream. Try opening it on YouTube or update yt-dlp.", "format")
    if "video unavailable" in text or "video has been removed" in text:
        return StreamingError("This video is unavailable or has been removed from YouTube.", "unavailable")
    if "failed to resolve" in text or "unable to download" in text or "timed out" in text:
        return StreamingError("YouTube could not be reached. Check your connection and try again.", "network")
    return StreamingError("YouTube could not complete this request. Try again or open the video on YouTube.", "youtube")


def video_id(value):
    if not isinstance(value, str):
        raise StreamingError("Enter a YouTube video URL.")
    if VIDEO_ID.fullmatch(value):
        return value
    parsed = youtube_url(value)
    parts = parsed.path.strip("/").split("/")
    identity = parts[0] if parsed.hostname == "youtu.be" else (
        parse_qs(parsed.query).get("v", [""])[0] if parts == ["watch"] else
        parts[1] if len(parts) == 2 and parts[0] in ("shorts", "live", "embed") else "")
    if not VIDEO_ID.fullmatch(identity):
        raise StreamingError("Enter a single YouTube video URL.")
    return identity


def youtube_url(value):
    try:
        parsed = urlsplit(value.strip())
        if (parsed.scheme != "https" or parsed.hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or any(ord(c) < 32 for c in value)):
            raise ValueError()
        return parsed
    except (ValueError, AttributeError):
        raise StreamingError("Use an HTTPS YouTube URL.") from None


def channel_url(value):
    if not isinstance(value, str):
        raise StreamingError("Enter a YouTube channel URL or @handle.")
    value = value.strip()
    if value.startswith("@"):
        value = "https://www.youtube.com/" + value
    parsed = youtube_url(value)
    parts = parsed.path.strip("/").split("/")
    if parts[-1] in ("videos", "streams", "shorts"):
        parts.pop()
    if len(parts) == 1 and re.fullmatch(r"@[\w.-]{1,100}", parts[0]):
        return "https://www.youtube.com/" + parts[0]
    if len(parts) == 2 and ((parts[0] == "channel" and CHANNEL_ID.fullmatch(parts[1]))
                            or (parts[0] in ("c", "user") and re.fullmatch(r"[\w.-]{1,100}", parts[1]))):
        return "https://www.youtube.com/" + "/".join(parts)
    raise StreamingError("Enter a YouTube channel URL or @handle.")


def watch_url(identity):
    return "https://www.youtube.com/watch?v=" + video_id(identity)


def channel_id(value):
    if isinstance(value, str):
        if CHANNEL_ID.fullmatch(value):
            return value
        try:
            path = urlsplit(value).path.strip("/").split("/")
            if len(path) == 2 and path[0] == "channel" and CHANNEL_ID.fullmatch(path[1]):
                return path[1]
        except ValueError:
            pass
    return ""


def members_only(item):
    return item.get("availability") in ("subscriber_only", "premium_only")


def record(raw):
    identity = str(raw.get("id") or "")
    if not VIDEO_ID.fullmatch(identity):
        return None
    thumbnail = str(raw.get("thumbnail") or "")
    if not thumbnail:
        thumbnail = next((str(t.get("url") or "") for t in reversed(raw.get("thumbnails") or []) if isinstance(t, dict)), "")
    try:
        channel = channel_url(raw.get("channel_url") or raw.get("uploader_url") or "")
    except StreamingError:
        channel = ""
    try:
        handle = channel_url(raw.get("uploader_url") or "")
    except StreamingError:
        handle = ""
    def number(value):
        return max(0, int(value)) if isinstance(value, (int, float)) and value < 10**12 else 0
    chapters = [dict(title=str(c.get("title") or "Chapter")[:500], start=number(c.get("start_time")))
                for c in (raw.get("chapters") or [])[:300] if isinstance(c, dict)]
    date = str(raw.get("upload_date") or raw.get("release_date") or "")
    try:
        date = datetime.strptime(date, "%Y%m%d").date().isoformat()
    except ValueError:
        date = ""
    return dict(id=identity, url=watch_url(identity), title=str(raw.get("title") or "Untitled video")[:1000],
                creator=str(raw.get("channel") or raw.get("uploader") or raw.get("artist") or "")[:500],
                channel=channel, channelHandle=handle, channelId=channel_id(raw.get("channel_id")) or channel_id(channel),
                thumbnail=thumbnail if thumbnail.startswith("https://") else "",
                backdrop="https://i.ytimg.com/vi/" + identity + "/sd2.jpg",
                availability=str(raw.get("availability") or ""),
                duration=number(raw.get("duration")), views=number(raw.get("view_count")),
                date=date,
                description=str(raw.get("description") or "")[:30000], chapters=chapters,
                artist=str(raw.get("artist") or raw.get("uploader") or raw.get("channel") or "Unknown artist")[:500],
                album=str(raw.get("album") or "YouTube")[:500], live=bool(raw.get("is_live")), upcoming=raw.get("live_status") == "is_upcoming")


class Commands:
    def __init__(self):
        self.lock = threading.Lock()
        self.processes = set()
        self.partials = set()
        self.closed = False

    @staticmethod
    def terminate(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=0.7)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=1)
        except ProcessLookupError:
            pass

    def run(self, command, timeout=90, on_line=None):
        check_cancelled()
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            with self.lock:
                if self.closed:
                    raise StreamingError("Streaming has closed.")
                try:
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors, start_new_session=True)
                except OSError:
                    raise StreamingError("A Streaming tool could not start. Check yt-dlp, FFmpeg and Deno are installed.") from None
                self.processes.add(process)
            started = time.monotonic()
            offset, pending = 0, b""
            try:
                while True:
                    check_cancelled()
                    if time.monotonic() - started > timeout:
                        raise StreamingError("The request timed out. Try again.")
                    # pread leaves the child's shared output offset untouched.
                    chunk = os.pread(output.fileno(), 1024 * 1024, offset)
                    offset += len(chunk)
                    pending += chunk
                    if offset > 24 * 1024 * 1024:
                        raise StreamingError("YouTube returned too much data. Narrow the request.")
                    if on_line:
                        while b"\n" in pending:
                            line, _, pending = pending.partition(b"\n")
                            on_line(line.decode("utf-8", "replace"))
                    if process.poll() is not None and not chunk:
                        break
                    time.sleep(0.1)
                if process.returncode:
                    raise command_error(os.pread(errors.fileno(), 65536, 0).decode("utf-8", "replace"))
                if on_line and pending:
                    on_line(pending.decode("utf-8", "replace"))
                return pending.decode("utf-8", "replace")
            finally:
                # Release helpers even when the leading process already exited.
                self.terminate(process)
                with self.lock:
                    self.processes.discard(process)

    def ytdlp(self, args, **kwargs):
        binary = shutil.which("yt-dlp")
        if not binary:
            raise StreamingError("Install yt-dlp and Deno to use Streaming.")
        return self.run([binary, "--ignore-config", "--no-plugin-dirs", "--no-remote-components",
                         "--no-playlist", "--socket-timeout", "15", "--retries", "2", "--fragment-retries", "2", *args], **kwargs)

    def extract(self, target, flat=False, start=1, count=24):
        args = ["--dump-single-json", "--skip-download"]
        if flat:
            args += ["--flat-playlist", "--playlist-start", str(start), "--playlist-end", str(start + count - 1)]
        else:
            # Metadata is useful even when membership/sign-in prevents media access.
            args += ["--ignore-no-formats-error"]
        text = self.ytdlp([*args, "--", target])
        try:
            result = json.loads(text)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except ValueError:
            raise StreamingError("YouTube returned an unreadable response.") from None

    def details(self, identity):
        result = record(self.extract(watch_url(identity)))
        if not result:
            raise StreamingError("The video is unavailable.")
        return result

    def close(self):
        with self.lock:
            self.closed = True
            processes = list(self.processes)
            partials = list(self.partials)
        for process in processes:
            self.terminate(process)
        for directory in partials:
            shutil.rmtree(directory, ignore_errors=True)

    @contextmanager
    def staging(self, directory):
        with self.lock:
            if self.closed:
                raise StreamingError("Streaming has closed.")
            stage = Path(tempfile.mkdtemp(prefix=".streaming-", dir=directory))
            self.partials.add(stage)
        try:
            yield stage
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            with self.lock:
                self.partials.discard(stage)
