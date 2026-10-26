#!/usr/bin/env python3
"""Minimal qBittorrent search, queue, and identity-based library import worker."""

import concurrent.futures
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from http.cookiejar import CookieJar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spaces.movies.local import (
    EXTENSIONS,
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    LocalLibrary,
    destination,
    episode_numbers,
    identity,
    label,
    library_root,
    subtitle_associations,
)
from spaces.movies.scanner import (
    audio_tags,
    candidates,
    catalogue_match,
    guess,
    settled,
    sidecar_identity,
)

from spaces.movies.paths import DATA, SPACE

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "quickshell/desktop/integrations/torrents.json"



class TorrentError(Exception):
    pass


class QBitConnectionError(TorrentError):
    pass


class QBitClient:
    def __init__(self, config):
        url = str(config.get("url") or "http://127.0.0.1:8080").rstrip("/")
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise TorrentError(
                "qBittorrent url must be an http or https Web UI origin without a path."
            )
        self.url = url
        self.username = str(config.get("username") or "")
        self.password = str(config.get("password") or "")
        self.api_key = str(config.get("api_key") or "").strip()
        if not self.api_key and bool(self.username) != bool(self.password):
            raise TorrentError("Set both qBittorrent username and password in torrents.json.")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        self.lock = threading.RLock()
        self.logged_in = not self.username or bool(self.api_key)

    def _request(self, path, values=None, *, login=False):
        method = "POST" if values is not None else "GET"
        endpoint = "/api/v2/" + path.split("?", 1)[0]
        headers = {"Referer": self.url, "User-Agent": "MoviesSpace/1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if path == "torrents/add" and values is not None:
            boundary = "----MoviesSpace" + uuid.uuid4().hex
            body = (
                b"".join(
                    b"--"
                    + boundary.encode()
                    + b'\r\nContent-Disposition: form-data; name="'
                    + key.encode()
                    + b'"\r\n\r\n'
                    + str(value).encode()
                    + b"\r\n"
                    for key, value in values.items()
                )
                + b"--"
                + boundary.encode()
                + b"--\r\n"
            )
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        else:
            body = urllib.parse.urlencode(values).encode() if values is not None else None
            if values is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(
            self.url + "/api/v2/" + path, data=body, method=method, headers=headers
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                payload = response.read(4 * 1024 * 1024 + 1)
                if len(payload) > 4 * 1024 * 1024:
                    raise TorrentError("qBittorrent returned too much data.")
                return payload.decode("utf-8")
        except urllib.error.HTTPError as error:
            error.close()
            if error.code in (401, 403):
                self.logged_in = False
                if self.api_key:
                    raise TorrentError(
                        f"qBittorrent rejected the API key for {endpoint}. "
                        "API key authentication requires qBittorrent 5.2.0 or newer."
                    ) from None
                if not self.username:
                    raise TorrentError(
                        f"qBittorrent requires Web UI credentials for {endpoint}. Add them to torrents.json."
                    ) from None
                raise TorrentError(
                    f"qBittorrent rejected the Web UI credentials for {endpoint}."
                ) from None
            raise TorrentError(f"qBittorrent returned HTTP {error.code} for {endpoint}.") from None
        except OSError:
            raise QBitConnectionError(
                "Cannot reach the qBittorrent Web UI. Check torrents.json and that qBittorrent is running."
            ) from None
        except UnicodeError:
            raise TorrentError("qBittorrent returned an unreadable response.") from None

    def call(self, path, values=None):
        with self.lock:
            if not self.api_key and not self.logged_in and self.username:
                response = self._request(
                    "auth/login", {"username": self.username, "password": self.password}, login=True
                )
                if response.strip() != "Ok.":
                    raise TorrentError("qBittorrent rejected the Web UI credentials.")
                self.logged_in = True
            response = self._request(path, values)
            if response.strip() == "Fails.":
                raise TorrentError("qBittorrent could not complete the request.")
            if response.startswith(("{", "[")):
                try:
                    return json.loads(response)
                except ValueError:
                    raise TorrentError("qBittorrent returned invalid JSON.") from None
            return response.strip()


def search_query(title):
    parts = [str(title.get("title") or "").strip()]
    year = (
        ""
        if title.get("kind") == "tv"
        or (title.get("kind") == "music" and title.get("scope") == "artist")
        else str(
            title.get("year") or title.get("firstPublishYear") or title.get("releaseDate") or ""
        )[:4]
    )
    if re.fullmatch(r"\d{4}", year):
        parts.append(year)
    if title.get("kind") == "tv":
        if title.get("season") is not None:
            code = f"S{int(title['season']):02d}"
            if title.get("episode") is not None:
                code += f"E{int(title['episode']):02d}"
            parts.append(code)
        else:
            parts.append("complete")
    if title.get("kind") == "music" and title.get("scope") != "artist" and title.get("artist"):
        parts.insert(0, str(title["artist"]))
    if title.get("kind") == "music" and title.get("scope") == "artist":
        parts.append("discography")
    if title.get("kind") == "book" and title.get("author"):
        parts.append(str(title["author"]))
    return " ".join(filter(None, parts))


def result_row(result, title):
    name = str(result.get("fileName") or "")
    year = (
        ""
        if title.get("kind") == "tv"
        else str(
            title.get("year") or title.get("firstPublishYear") or title.get("releaseDate") or ""
        )[:4]
    )
    years = set(re.findall(r"(?<!\d)(?:18|19|20)\d{2}(?!\d)", name))
    wanted_season = (
        int(title["season"])
        if title.get("kind") == "tv" and title.get("season") is not None
        else None
    )
    wanted_episode = (
        (wanted_season, int(title["episode"]))
        if wanted_season is not None and title.get("episode") is not None
        else None
    )
    named_episode = episode_numbers(name)
    try:
        site = urllib.parse.urlsplit(str(result.get("siteUrl") or "")).hostname or ""
        description = str(result.get("descrLink") or "")
        if urllib.parse.urlsplit(description).scheme not in ("http", "https"):
            description = ""
    except ValueError:
        site, description = "", ""
    return {
        "name": name,
        "url": result.get("fileUrl") or "",
        "descriptionUrl": description,
        "site": site,
        "size": result.get("fileSize") or 0,
        "seeders": result.get("nbSeeders") or 0,
        "leechers": result.get("nbLeechers") or 0,
        "yearMismatch": bool(year and years and year not in years),
        "episodeMismatch": bool(
            wanted_episode and named_episode and wanted_episode != named_episode
        ),
        "seasonMismatch": bool(
            wanted_season is not None and named_episode and named_episode[0] != wanted_season
        ),
    }


class TorrentBackend:
    def __init__(self, config=CONFIG, data=DATA, client=None):
        self.config_path = Path(config)
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.library = LocalLibrary(self.data)
        self.client_override = client
        self.client = None
        self.client_config = None
        self.scan_pending = {}
        self.owned_searches = set()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS torrent_downloads ("
                "id TEXT PRIMARY KEY, search_url TEXT NOT NULL, save_path TEXT NOT NULL, "
                "title_json TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', "
                "torrent_hash TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS torrent_file_matches ("
                "job_id TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY(job_id,path))"
            )

    @staticmethod
    def job_tag(job_id):
        return SPACE + "-job-" + job_id

    def find_job_torrent(self, job_id, torrent_hash, torrents):
        # A title folder is shared by season/episode downloads. Never use it as identity.
        if torrent_hash:
            return next((t for t in torrents if t.get("hash") == torrent_hash), None)
        tagged = [
            t for t in torrents if any(
                job_id in value for value in str(t.get("tags") or "").split(",")
            )
        ]
        if tagged:
            return tagged[0]
        return None

    def torrent(self, torrent_hash):
        if not torrent_hash:
            return None
        return next(
            (t for t in self.qbit().call("torrents/info") if t.get("hash") == torrent_hash), None
        )

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.data / "library.sqlite", timeout=20)
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def import_lock(self, job_id):
        locks = self.data / "torrent-locks"
        locks.mkdir(exist_ok=True)
        with (locks / job_id).open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def config(self):
        try:
            data = json.loads(self.config_path.read_text())
        except FileNotFoundError:
            return {"url": "http://127.0.0.1:8080"}
        except (OSError, ValueError):
            raise TorrentError("Cannot read torrents.json. Check its JSON syntax.") from None
        if not isinstance(data, dict):
            raise TorrentError("torrents.json must contain a JSON object.")
        return data

    def qbit(self):
        if self.client_override is not None:
            return self.client_override
        config = self.config()
        fingerprint = (
            config.get("url"),
            config.get("username"),
            config.get("password"),
            config.get("api_key"),
        )
        if fingerprint != self.client_config:
            self.client = QBitClient(config)
            self.client_config = fingerprint
        return self.client

    def local_web_ui(self):
        host = urllib.parse.urlsplit(
            str(self.config().get("url") or "http://127.0.0.1:8080")
        ).hostname
        if host is None:
            return False
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except (ValueError, TypeError):
            return False

    @staticmethod
    def qbit_running():
        try:
            processes = Path("/proc").iterdir()
            for process in processes:
                if not process.name.isdigit():
                    continue
                try:
                    if process.stat().st_uid == os.getuid() and (
                        process / "comm"
                    ).read_text().strip().lower() in ("qbittorrent", "qbittorrent-nox"):
                        return True
                except (OSError, UnicodeError):
                    continue
        except OSError:
            pass
        return False

    @staticmethod
    def qbit_launcher():
        native = shutil.which("qbittorrent")
        if native:
            return [native]
        flatpak = shutil.which("flatpak")
        if flatpak:
            try:
                installed = subprocess.run(
                    [flatpak, "info", "--show-ref", "org.qbittorrent.qBittorrent"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
                if installed.returncode == 0:
                    return [flatpak, "run", "org.qbittorrent.qBittorrent"]
            except (OSError, subprocess.TimeoutExpired):
                pass
        return None

    def probe(self, request):
        try:
            return self.init(request) | {"connected": True, "canStart": False}
        except QBitConnectionError as error:
            local = self.local_web_ui()
            running = self.qbit_running() if local else False
            launcher = self.qbit_launcher() if local and not running else None
            return {
                "connected": False,
                "plugins": [],
                "canStart": bool(launcher),
                "error": str(error)
                if not local or running or launcher
                else "qBittorrent is not installed. Install it and enable its Web UI.",
            }

    def start_qbittorrent(self, request):
        if not self.local_web_ui():
            raise TorrentError("Only a local qBittorrent installation can be started here.")
        if self.qbit_running():
            return {"started": False}
        command = self.qbit_launcher()
        if not command:
            raise TorrentError("qBittorrent is not installed. Install it and enable its Web UI.")
        try:
            subprocess.Popen(
                ["uwsm", "app", "-t", "service", "--", *command],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            raise TorrentError(
                "Could not start qBittorrent. Launch it from your applications menu."
            ) from None
        return {"started": True}

    def move_torrent_files(self, torrent, assignments):
        """Let qBittorrent rename and relocate its own payload before indexing it."""
        if not assignments:
            return []
        save = Path(torrent.get("save_path") or "").resolve()
        kind = assignments[0][1]["kind"]
        planned = []
        locations = set()

        def identical(a, b):
            if a.stat().st_size != b.stat().st_size:
                return False

            def digest(path):
                value = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        value.update(block)
                return value.digest()

            return digest(a) == digest(b)

        for source, title, season, episode, preserve_name in assignments:
            source = Path(source)
            if (
                not source.is_file()
                or source.is_symlink()
                or not source.resolve().is_relative_to(save)
            ):
                raise ValueError("The completed torrent file is unavailable or unsafe.")
            target = destination(title, source, season, episode, preserve_name)
            location = target.parent.parent if kind == "tv" else target.parent
            locations.add(location)
            if target.exists() and target != source:
                association = self.library.source(target)
                if (
                    association["torrent_hash"] != torrent["hash"]
                    or Path(association["source_path"]) != source
                    or not identical(source, target)
                ):
                    raise ValueError("A file already exists at the library destination.")
            planned.append((source, target, location))
        targets = [target for _, target, _ in planned]
        if len(targets) != len(set(targets)):
            raise ValueError(
                "Several files would have the same library name. Review the selected files."
            )
        if len(locations) != 1:
            raise ValueError(
                "Torrent files must share one library folder before they can be moved."
            )
        location = locations.pop()
        subtitle_planned = []
        external_subtitles = []
        if kind in ("movie", "tv"):
            manifest = self.qbit().call(
                "torrents/files?" + urllib.parse.urlencode({"hash": torrent["hash"]})
            )
            owned = set()
            selected = set()
            for entry in manifest:
                relative = Path(entry.get("name") or "")
                path = save / relative
                if (
                    not relative.is_absolute()
                    and ".." not in relative.parts
                    and path.resolve().is_relative_to(save)
                    and not path.is_symlink()
                ):
                    owned.add(path)
                    if int(entry.get("priority", 1)) != 0 and path.is_file():
                        selected.add(path)
            source_folders = {source.parent for source, _, _ in planned}
            physical = [
                path
                for folder in source_folders
                for path in folder.iterdir()
                if path.is_file() and not path.is_symlink()
            ]
            videos = [path for path in physical if path.suffix.lower() in VIDEO_EXTENSIONS]
            subtitles = [path for path in physical if path.suffix.lower() in SUBTITLE_EXTENSIONS]
            associations = subtitle_associations(videos, subtitles)
            for source, target, _ in planned:
                for subtitle, remainder in associations.get(source, []):
                    if subtitle in owned and subtitle not in selected:
                        continue
                    renamed = target.with_name(target.stem + remainder + subtitle.suffix.lower())
                    if renamed.exists() and renamed != subtitle:
                        raise ValueError(
                            f"A subtitle already exists at the library destination: {renamed.name}"
                        )
                    if subtitle in owned:
                        subtitle_planned.append((subtitle, renamed, location))
                    else:
                        external_subtitles.append((subtitle, renamed, location))
            names = [target for _, target, _ in subtitle_planned + external_subtitles]
            if len(names) != len(set(names)):
                raise ValueError("Several subtitles would have the same library name.")
        location.mkdir(parents=True, exist_ok=True)
        torrent_hash = str(torrent["hash"])
        backups = []
        moved_external = []
        try:
            for source, target, _ in external_subtitles:
                if source != target:
                    shutil.move(str(source), str(target))
                    moved_external.append((source, target))
            if torrent.get("auto_tmm"):
                self.qbit().call(
                    "torrents/setAutoManagement", {"hashes": torrent_hash, "enable": "false"}
                )
            for index, (source, target, _) in enumerate(planned + subtitle_planned):
                # Music tracks can already be registered while the rest of an album is matched.
                if index < len(planned) and target.exists() and target != source:
                    backup = target.with_name(target.name + "." + SPACE + "-backup-" + uuid.uuid4().hex)
                    target.rename(backup)
                    backups.append((target, backup))
                old = str(source.relative_to(save))
                new = str(target.relative_to(location))
                if old != new:
                    self.qbit().call(
                        "torrents/renameFile",
                        {"hash": torrent_hash, "oldPath": old, "newPath": new},
                    )
            if save != location.resolve():
                self.qbit().call(
                    "torrents/setLocation", {"hashes": torrent_hash, "location": str(location)}
                )
            for _, target, _ in planned + subtitle_planned + external_subtitles:
                deadline = time.monotonic() + 15
                while not target.is_file() and time.monotonic() < deadline:
                    time.sleep(0.1)
                if not target.is_file():
                    raise ValueError(
                        "qBittorrent has not finished moving the file. Retry after it settles."
                    )
        except Exception:
            for source, target in reversed(moved_external):
                if target.exists():
                    shutil.move(str(target), str(source))
            for target, backup in backups:
                if not target.exists():
                    backup.rename(target)
                elif identical(target, backup):
                    backup.unlink()
            raise
        for _, backup in backups:
            backup.unlink(missing_ok=True)
        return [(source, target) for source, target, _ in planned]

    def episode_assignments(self, assignments, catalogue=None):
        """Attach episode metadata per file, fetching each season only once per import."""
        seasons = {}
        enriched = []
        for source, title, season, episode, preserve in assignments:
            if title["kind"] != "tv":
                enriched.append((source, title, season, episode, preserve))
                continue
            numbers = (
                (season, episode)
                if season is not None and episode is not None
                else episode_numbers(Path(source).name)
            )
            if not numbers:
                enriched.append((source, title, season, episode, preserve))
                continue
            season, episode = map(int, numbers)
            supplied = (
                title.get("episodeTitle")
                if (
                    title.get("episode") is None
                    or (
                        title.get("season") is not None
                        and (int(title["season"]), int(title["episode"])) == (season, episode)
                    )
                )
                else ""
            )
            if supplied and re.fullmatch(r"(?i)Episode\s+\d+", supplied):
                supplied = ""
            key = (identity(title), season)
            if not supplied and key not in seasons:
                names = {}
                try:
                    if catalogue is None:
                        from spaces.movies.backend import Backend

                        catalogue = Backend(data=self.data)
                    page = ""
                    seen = set()
                    for _ in range(100):
                        result = catalogue.episodes(
                            {"title": title, "season": str(season), "page": page}
                        )
                        names.update(
                            {
                                int(row["number"]): row.get("title") or ""
                                for row in result.get("items", [])
                            }
                        )
                        page = result.get("next") or ""
                        if not page or page in seen:
                            break
                        seen.add(page)
                except Exception:
                    # Provider availability must not block a completed download.
                    pass
                seasons[key] = names
            name = (
                supplied
                or seasons.get(key, {}).get(episode)
                or guess(Path(source), "tv").get("episodeTitle")
                or ""
            )
            if re.fullmatch(r"(?i)Episode\s+\d+", name):
                name = ""
            item = {
                key: value
                for key, value in title.items()
                if key not in ("season", "episode", "episodeTitle")
            }
            enriched.append((source, item | {"episodeTitle": name}, season, episode, preserve))
        return enriched

    def import_torrent_files(self, torrent, assignments):
        assignments = self.episode_assignments(assignments)
        moved = self.move_torrent_files(torrent, assignments)
        for (source, target), (_, title, season, episode, preserve_name) in zip(
            moved, assignments, strict=True
        ):
            self.library.add(
                title,
                target,
                season=season,
                episode=episode,
                preserve_name=preserve_name,
                torrent_hash=torrent["hash"],
                source_path=source,
                release_name=str(torrent.get("name") or source.name),
            )
            self.library.replace_registered_path(source, target)
        return [str(target) for _, target in moved]

    def refresh_registered_episodes(self, root, torrents, catalogue):
        """A requested scan also adds missing names to previously indexed episodes."""
        with self.db() as db:
            rows = db.execute(
                "SELECT f.path,f.title_json,f.season,f.episode,s.torrent_hash FROM local_files f "
                "JOIN local_sources s ON s.path=f.path WHERE f.kind='tv'"
            ).fetchall()
        pending = []
        hashes = {}
        root = root.resolve()
        for path, payload, season, episode, torrent_hash in rows:
            source = Path(path)
            title = json.loads(payload)
            if (
                title.get("episodeTitle")
                or not source.is_file()
                or source.is_symlink()
                or not (source.resolve() == root or source.resolve().is_relative_to(root))
            ):
                continue
            pending.append((source, title, season, episode, False))
            hashes[source] = torrent_hash
            if len(pending) >= 500:
                break
        groups = {}
        for assignment in self.episode_assignments(pending, catalogue):
            source, title, season, episode, _ = assignment
            if title.get("episodeTitle"):
                torrent_hash = hashes[source]
                groups.setdefault((torrent_hash, None if torrent_hash else source), []).append(
                    assignment
                )
        imported, errors = [], []
        for (torrent_hash, _), assignments in groups.items():
            try:
                if torrent_hash:
                    torrent = next((t for t in torrents if t.get("hash") == torrent_hash), None)
                    if not torrent or not settled(torrent):
                        continue
                    targets = self.import_torrent_files(torrent, assignments)
                else:
                    targets = []
                    for source, title, season, episode, _ in assignments:
                        target = self.library.add(
                            title, source, season=season, episode=episode, move=True
                        )
                        self.library.replace_registered_path(source, target)
                        targets.append(target)
                imported.extend(
                    {"source": str(source), "path": target, "title": title["title"]}
                    for (source, title, _, _, _), target in zip(assignments, targets, strict=True)
                )
            except (TorrentError, OSError, ValueError) as error:
                errors.append(str(error))
        return imported, errors

    def init(self, request):
        plugins = self.qbit().call("search/plugins")
        enabled = [p["name"] for p in plugins if p.get("enabled")]
        return {"plugins": enabled, "configured": True}

    def search(self, request):
        pattern = str(request.get("query") or search_query(request.get("title") or {})).strip()
        if len(pattern) < 2 or len(pattern) > 250:
            raise TorrentError("Enter a search term between 2 and 250 characters.")
        if not self.init(request)["plugins"]:
            raise TorrentError(
                "Enable at least one qBittorrent search plugin in qBittorrent first."
            )
        result = self.qbit().call(
            "search/start", {"pattern": pattern, "plugins": "enabled", "category": "all"}
        )
        self.owned_searches.add(int(result["id"]))
        return {"id": result["id"], "query": pattern}

    def results(self, request):
        job = int(request["job_id"])
        offset = max(0, int(request.get("offset") or 0))
        result = self.qbit().call(
            "search/results?" + urllib.parse.urlencode({"id": job, "limit": 100, "offset": offset})
        )
        title = request.get("title") or {}
        rows = [result_row(row, title) for row in result.get("results", [])]
        rows.sort(
            key=lambda row: (
                row["yearMismatch"],
                row["seasonMismatch"],
                row["episodeMismatch"],
                -int(row["seeders"] or 0),
            )
        )
        return {
            "items": rows,
            "running": result.get("status") == "Running",
            "total": result.get("total", 0),
        }

    def status(self, request):
        job = int(request["job_id"])
        states = self.qbit().call("search/status?" + urllib.parse.urlencode({"id": job}))
        state = next((item for item in states if int(item.get("id", -1)) == job), None)
        if state is None:
            raise TorrentError("This qBittorrent search is no longer available.")
        return {"running": state.get("status") == "Running", "total": state.get("total", 0)}

    def stop(self, request):
        job = int(request["job_id"])
        try:
            self.qbit().call("search/stop", {"id": job})
        except TorrentError:
            pass
        try:
            self.qbit().call("search/delete", {"id": job})
        except TorrentError:
            pass
        self.owned_searches.discard(job)
        return True

    def shutdown(self):
        for job in tuple(self.owned_searches):
            self.stop({"job_id": job})

    def queue(self, request):
        title = dict(request.get("title") or {})
        identifier = identity(title)
        kind = title["kind"]
        if kind not in EXTENSIONS:
            raise TorrentError("This catalogue type is not supported for imports.")
        url = str(request.get("url") or "")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("magnet", "http", "https"):
            raise TorrentError("Search result must provide a magnet or torrent URL.")
        if len(url) > 8192:
            raise TorrentError("The torrent URL is too long.")
        if "\r" in url or "\n" in url:
            raise TorrentError("The torrent URL must contain one link.")
        selected = request.get("selected_files")
        priorities = ""
        if selected is not None:
            metadata = self.qbit().call("torrents/fetchMetadata", {"source": url})
            files = metadata.get("info", {}).get("files", [])
            if not files:
                raise TorrentError("Torrent file list is still loading. Try again in a moment.")
            selected = {int(index) for index in selected}
            audio = {
                index
                for index, file in enumerate(files)
                if Path(file.get("path") or "").suffix.lower() in EXTENSIONS["music"]
            }
            if kind != "music" or not selected or not selected.issubset(audio):
                raise TorrentError("Select at least one audio file from this torrent.")
            priorities = ",".join("1" if index in selected else "0" for index in range(len(files)))
        job_id = uuid.uuid4().hex
        save = (
            library_root(kind) / label(title)
            if kind in ("movie", "tv")
            else self.data / "torrents" / job_id
        ).resolve()
        existing = self.qbit().call("torrents/info")
        magnet_hash = re.search(r"(?i)(?:[?&])xt=urn:btih:([a-f0-9]{40})(?:&|$)", url)
        if magnet_hash and any(
            str(t.get("hash") or "").lower() == magnet_hash[1].lower() for t in existing
        ):
            raise TorrentError(
                "This torrent is already in qBittorrent. Scan it from Local when complete."
            )
        with self.db() as db:
            duplicate = db.execute(
                "SELECT id FROM torrent_downloads WHERE search_url=? AND status<>'imported'", (url,)
            ).fetchone()
        if duplicate:
            raise TorrentError(
                "This download is already tracked. Check its progress or review its files."
            )
        save.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute(
                "INSERT INTO torrent_downloads(id,search_url,save_path,title_json,status,message,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (job_id, url, str(save), json.dumps(title), "queued", "", time.time()),
            )
        try:
            # A unique tag links this job even when several downloads share a title folder.
            values = {
                "urls": url,
                "savepath": str(save),
                "autoTMM": "false",
                "tags": SPACE + "," + self.job_tag(job_id),
            }
            if priorities:
                values["filePriorities"] = priorities
            self.qbit().call("torrents/add", values)
        except Exception:
            with self.db() as db:
                db.execute("DELETE FROM torrent_downloads WHERE id=?", (job_id,))
            try:
                save.rmdir()
            except OSError:
                pass
            raise
        return {"id": job_id, "titleId": identifier, "savePath": str(save)}

    def inspect(self, request):
        url = str(request.get("url") or "")
        if urllib.parse.urlsplit(url).scheme not in ("magnet", "http", "https") or len(url) > 8192:
            raise TorrentError("Choose a valid search result.")
        metadata = self.qbit().call("torrents/fetchMetadata", {"source": url})
        files = metadata.get("info", {}).get("files", [])
        return {
            "ready": bool(files),
            "files": [
                {
                    "index": index,
                    "path": file.get("path") or "",
                    "size": file.get("length") or 0,
                    "audio": Path(file.get("path") or "").suffix.lower() in EXTENSIONS["music"],
                }
                for index, file in enumerate(files)
            ],
        }

    def jobs(self, request):
        with self.db() as db:
            saved = db.execute(
                "SELECT id,save_path,title_json,status,message,torrent_hash,created_at "
                "FROM torrent_downloads ORDER BY rowid DESC"
            ).fetchall()
        if request.get("kind"):
            saved = [row for row in saved if json.loads(row[2])["kind"] == request["kind"]]
        active = [row for row in saved if row[3] not in ("imported", "review")]
        torrents = []
        if active:
            torrents = self.qbit().call("torrents/info")
        output = []
        for job_id, save_path, payload, status, message, torrent_hash, created_at in saved:
            title = json.loads(payload)
            torrent = self.find_job_torrent(job_id, torrent_hash, torrents)
            if torrent and not torrent_hash:
                with self.db() as db:
                    db.execute(
                        "UPDATE torrent_downloads SET torrent_hash=? WHERE id=?",
                        (torrent["hash"], job_id),
                    )
            progress = float(torrent.get("progress") or 0) if torrent else 0
            if status in ("imported", "review"):
                progress = 1.0
            elif torrent and settled(torrent):
                with self.import_lock(job_id) as acquired:
                    if acquired:
                        with self.db() as db:
                            current = db.execute(
                                "SELECT status,message FROM torrent_downloads WHERE id=?", (job_id,)
                            ).fetchone()
                        status, message = current if current else (status, message)
                        if status not in ("imported", "review"):
                            try:
                                self.import_job(title, torrent)
                                status, message = "imported", ""
                            except (TorrentError, OSError, ValueError) as error:
                                status, message = "review", str(error)
                            with self.db() as db:
                                db.execute(
                                    "UPDATE torrent_downloads SET status=?,message=? WHERE id=?",
                                    (status, message, job_id),
                                )
            if not torrent and status == "queued" and time.time() - created_at > 120:
                message = "qBittorrent did not add this torrent. Check for a duplicate or invalid search result."
            output.append(
                {
                    "id": job_id,
                    "titleId": identity(title),
                    "kind": title["kind"],
                    "savePath": torrent["save_path"] if torrent else save_path,
                    "active": status not in ("imported", "review")
                    and (bool(torrent) or not message),
                    "title": title.get("title") or "",
                    "status": status
                    if status in ("imported", "review")
                    else (torrent.get("state") if torrent else status),
                    "progress": progress,
                    "total": int(torrent.get("size") or 0) if torrent else 0,
                    "downloaded": int(torrent.get("downloaded") or 0) if torrent else 0,
                    "speed": int(torrent.get("dlspeed") or 0) if torrent else 0,
                    "eta": int(torrent.get("eta") or 0)
                    if torrent and torrent.get("eta") not in (None, 8640000)
                    else None,
                    "record": title,
                    "message": message,
                }
            )
        return output

    def import_job(self, title, torrent):
        save = Path(torrent["save_path"]).resolve()
        files = self.qbit().call(
            "torrents/files?" + urllib.parse.urlencode({"hash": torrent["hash"]})
        )
        candidates = []
        for file in files:
            if int(file.get("priority") or 0) == 0:
                continue
            relative = Path(file.get("name") or "")
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Torrent contains an unsafe file path.")
            source = save / relative
            if (
                not source.resolve().is_relative_to(save)
                or source.suffix.lower() not in EXTENSIONS[title["kind"]]
                or not source.is_file()
                or source.is_symlink()
            ):
                continue
            if ("sample" in source.stem.casefold() and title["kind"] in ("movie", "tv")) or (
                title["kind"] in ("movie", "tv") and source.stat().st_size < 1024 * 1024
            ):
                continue
            candidates.append(source)
        if not candidates:
            raise ValueError(
                "No supported completed files found; inspect this torrent in qBittorrent."
            )
        if title["kind"] == "music" and title.get("scope") in ("album", "artist"):
            raise ValueError("Match each audio file to a catalogue song before importing.")
        if title["kind"] == "movie":
            if len(candidates) != 1:
                raise ValueError(
                    "Several movie files found; choose the correct file in qBittorrent first."
                )
            year = str(title.get("year") or "")[:4]
            named_years = set(re.findall(r"(?<!\d)(?:18|19|20)\d{2}(?!\d)", candidates[0].stem))
            if year and named_years and year not in named_years:
                raise ValueError(
                    "The downloaded movie filename names a different year; review the file."
                )
            self.import_torrent_files(torrent, [(candidates[0], title, None, None, False)])
        elif title["kind"] == "tv":
            if (
                len(candidates) > 1
                and title.get("season") is not None
                and title.get("episode") is not None
            ):
                raise ValueError(
                    "Several episode files found; choose the correct one for this episode."
                )
            assignments = []
            for source in candidates:
                numbers = episode_numbers(source.name)
                if (
                    not numbers
                    and title.get("season") is not None
                    and title.get("episode") is not None
                ):
                    numbers = (int(title["season"]), int(title["episode"]))
                if (
                    numbers
                    and title.get("season") is not None
                    and title.get("episode") is not None
                    and numbers != (int(title["season"]), int(title["episode"]))
                ):
                    raise ValueError(
                        "The downloaded episode number differs from the selected episode."
                    )
                if (
                    numbers
                    and title.get("season") is not None
                    and numbers[0] != int(title["season"])
                ):
                    raise ValueError("The downloaded season differs from the selected season.")
                if not numbers:
                    raise ValueError("At least one TV file has no S01E01 episode number.")
                assignments.append((source, title, numbers[0], numbers[1], False))
            self.import_torrent_files(torrent, assignments)
        elif title["kind"] == "game":
            self.import_torrent_files(
                torrent, [(source, title, None, None, len(candidates) > 1) for source in candidates]
            )
        else:
            if len(candidates) != 1:
                raise ValueError("Several files found; this item needs a manual import.")
            self.import_torrent_files(torrent, [(candidates[0], title, None, None, False)])

    def review(self, request):
        job_id = str(request["job_id"])
        with self.db() as db:
            row = db.execute(
                "SELECT title_json,torrent_hash FROM torrent_downloads WHERE id=?", (job_id,)
            ).fetchone()
        if not row:
            raise TorrentError("This download is no longer tracked.")
        payload = json.loads(row[0])
        torrent = self.torrent(row[1])
        if not torrent or float(torrent.get("progress") or 0) < 1:
            raise TorrentError("This download is not complete yet.")
        save = Path(torrent["save_path"]).resolve()
        with self.db() as db:
            imported = {
                row[0]
                for row in db.execute(
                    "SELECT path FROM torrent_file_matches WHERE job_id=?", (job_id,)
                )
            }
        files = self.qbit().call(
            "torrents/files?" + urllib.parse.urlencode({"hash": torrent["hash"]})
        )
        result = []
        for file in files:
            relative = Path(file.get("name") or "")
            source = save / relative
            if (
                int(file.get("priority", 1)) != 0
                and not relative.is_absolute()
                and ".." not in relative.parts
                and source.resolve().is_relative_to(save)
                and source.is_file()
                and not source.is_symlink()
                and source.suffix.lower() in EXTENSIONS[payload["kind"]]
                and str(relative) not in imported
            ):
                result.append(
                    {
                        "path": str(relative),
                        "size": source.stat().st_size,
                        "tags": audio_tags(source) if payload["kind"] == "music" else {},
                    }
                )
        return result

    def import_selected(self, request):
        job_id = str(request["job_id"])
        selected = str(request.get("path") or "")
        valid = {item["path"] for item in self.review(request)}
        if selected not in valid:
            raise TorrentError("Choose a completed file from this download.")
        with self.db() as db:
            row = db.execute(
                "SELECT title_json,torrent_hash FROM torrent_downloads WHERE id=?", (job_id,)
            ).fetchone()
        title = json.loads(row[0])
        torrent = self.torrent(row[1])
        if not torrent:
            raise TorrentError("The source torrent is no longer available.")
        matching_music = title["kind"] == "music" and title.get("scope") in ("album", "artist")
        if matching_music:
            track = request.get("track")
            if (
                not isinstance(track, dict)
                or track.get("kind") != "song"
                or not track.get("id")
                or not track.get("title")
            ):
                raise TorrentError("Choose a catalogue song for this audio file.")
            title = dict(track, kind="music")
        for field in ("artist", "album", "releaseDate"):
            if field in request and isinstance(request[field], str):
                title[field] = request[field].strip()
        try:
            source = Path(torrent["save_path"]) / selected
            if matching_music:
                target = self.library.add(title, source, torrent_hash=torrent["hash"])
            else:
                target = self.import_torrent_files(
                    torrent, [(source, title, request.get("season"), request.get("episode"), False)]
                )[0]
        except (OSError, ValueError) as error:
            raise TorrentError(str(error)) from None
        if matching_music:
            with self.db() as db:
                db.execute(
                    "INSERT OR IGNORE INTO torrent_file_matches VALUES (?,?)", (job_id, selected)
                )
            remaining = len(self.review(request))
            status = "review" if remaining else "imported"
            message = f"{remaining} audio files remain to match." if remaining else ""
            if not remaining:
                with self.db() as db:
                    rows = db.execute(
                        "SELECT f.title_json,s.source_path FROM local_files f "
                        "JOIN local_sources s ON s.path=f.path "
                        "WHERE s.torrent_hash=?",
                        (torrent["hash"],),
                    ).fetchall()
                assignments = [
                    (Path(path), json.loads(payload), None, None, False)
                    for payload, path in rows
                    if Path(path).is_file()
                ]
                if assignments:
                    self.move_torrent_files(torrent, assignments)
        else:
            remaining, status, message = 0, "imported", ""
        with self.db() as db:
            db.execute(
                "UPDATE torrent_downloads SET status=?,message=? WHERE id=?",
                (status, message, job_id),
            )
        return {"path": target, "remaining": remaining}

    def scan(self, request):
        kind = str(request.get("kind") or "")
        if kind not in EXTENSIONS:
            raise TorrentError("Choose a supported Local library.")
        given = str(request.get("path") or "").strip()
        root = Path(given or library_root(kind)).expanduser()
        if given and not root.exists():
            raise TorrentError("The scan folder or file does not exist.")
        # Register completed tracked downloads before looking for untracked files.
        try:
            self.jobs({"kind": kind})
        except TorrentError:
            pass
        with self.db() as db:
            managed = {
                row[0]
                for row in db.execute(
                    "SELECT save_path FROM torrent_downloads WHERE status<>'imported'"
                )
            }
            managed_hashes = {
                row[0] for row in db.execute("SELECT torrent_hash FROM torrent_downloads") if row[0]
            }
        catalogue = None
        if kind in ("movie", "tv"):
            from spaces.movies.backend import Backend

            catalogue = Backend(data=self.data)
        warning = ""
        try:
            qbit = self.qbit()
            torrents = qbit.call("torrents/info")
        except TorrentError as error:
            qbit, torrents = None, []
            warning = str(error) + " Scanned the folder only."
        self.scan_pending = {}
        imported, review, checked = [], [], 0
        if kind == "tv":
            imported, rename_errors = self.refresh_registered_episodes(root, torrents, catalogue)
            if rename_errors:
                warning = " ".join([warning, *rename_errors]).strip()
        with self.db() as db:
            registered = {row[0] for row in db.execute("SELECT path FROM local_files")}
        discovered = list(candidates(kind, root, qbit, managed, torrents, managed_hashes))
        source_videos = [entry["path"] for entry in discovered] if kind in ("movie", "tv") else []
        torrent_counts = {}
        for item in discovered:
            if item["torrent_hash"]:
                torrent_counts[item["torrent_hash"]] = (
                    torrent_counts.get(item["torrent_hash"], 0) + 1
                )
        processed = set()
        for item in discovered:
            path = Path(item["path"])
            if str(path) in registered or str(path) in processed or not path.is_file():
                continue
            checked += 1
            if checked > 500:
                break
            if kind == "tv" and item["torrent_hash"] and torrent_counts[item["torrent_hash"]] > 1:
                group = [
                    entry
                    for entry in discovered
                    if entry["torrent_hash"] == item["torrent_hash"]
                    and entry["path"] not in registered
                    and Path(entry["path"]).is_file()
                ]
                parsed_group = [guess(Path(entry["path"]), kind) for entry in group]
                names = {
                    re.sub(r"\W+", "", parsed.get("title", "").casefold())
                    for parsed in parsed_group
                }
                if len(names) == 1 and all(
                    parsed.get("season") is not None and parsed.get("episode") is not None
                    for parsed in parsed_group
                ):
                    title = sidecar_identity(Path(group[0]["path"]), kind) or catalogue_match(
                        catalogue, kind, parsed_group[0]
                    )
                    if title:
                        title["kind"] = kind
                        torrent = next(t for t in torrents if t["hash"] == item["torrent_hash"])
                        assignments = [
                            (Path(entry["path"]), title, parsed["season"], parsed["episode"], False)
                            for entry, parsed in zip(group, parsed_group, strict=True)
                        ]
                        try:
                            targets = self.import_torrent_files(torrent, assignments)
                            imported.extend(
                                {
                                    "source": entry["path"],
                                    "path": target,
                                    "title": title.get("title"),
                                }
                                for entry, target in zip(group, targets, strict=True)
                            )
                            processed.update(entry["path"] for entry in group)
                            checked += len(group) - 1
                            continue
                        except (TorrentError, OSError, ValueError) as error:
                            item["reason"] = str(error)
            parsed = guess(path, kind)
            title = sidecar_identity(path, kind) or (
                catalogue_match(catalogue, kind, parsed) if catalogue else None
            )
            item.update(guess=parsed)
            if item["torrent_hash"] and torrent_counts[item["torrent_hash"]] > 1:
                title = None
                item["reason"] = (
                    "This torrent contains several media files; match them together in qBittorrent."
                )
            if title:
                title["kind"] = kind
                try:
                    if item["torrent_hash"]:
                        torrent = next(t for t in torrents if t["hash"] == item["torrent_hash"])
                        target = self.import_torrent_files(
                            torrent,
                            [
                                (
                                    path,
                                    title,
                                    parsed.get("season"),
                                    parsed.get("episode"),
                                    kind == "game",
                                )
                            ],
                        )[0]
                    else:
                        _, title, _, _, _ = self.episode_assignments(
                            [(path, title, parsed.get("season"), parsed.get("episode"), False)],
                            catalogue,
                        )[0]
                        target = self.library.add(
                            title,
                            path,
                            season=parsed.get("season"),
                            episode=parsed.get("episode"),
                            preserve_name=kind == "game",
                            move=True,
                            association_videos=source_videos,
                        )
                    imported.append(
                        {"source": str(path), "path": target, "title": title.get("title")}
                    )
                    continue
                except (TorrentError, OSError, ValueError) as error:
                    item["reason"] = str(error)
            else:
                item.setdefault("reason", "Choose the matching catalogue title.")
            token = uuid.uuid4().hex
            stat = path.stat()
            self.scan_pending[token] = item | {
                "kind": kind,
                "stat": (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns),
                "association_videos": source_videos,
            }
            review.append(item | {"token": token})
        return {
            "imported": imported,
            "review": review,
            "checked": checked,
            "limited": checked > 500,
            "warning": warning,
        }

    def scan_lookup(self, request):
        token = str(request.get("token") or "")
        item = self.scan_pending.get(token)
        if not item:
            raise TorrentError("Scan this folder again before matching files.")
        query = str(request.get("query") or item["guess"].get("title") or "").strip()
        if len(query) < 2:
            return []
        if item["kind"] == "music":
            from spaces.music.backend import search_page, MusicError
            try:
                return [dict(song, kind="music") for song in search_page({"query":query,"category":"songs"})["items"]]
            except MusicError as error:
                raise TorrentError(str(error)) from None

        if item["kind"] == "book":
            from spaces.books.backend import BooksBackend, BooksError
            catalogue = BooksBackend(data=self.data)
            try:
                matches = catalogue.browse({"query": query})["items"]
                return [book | {"kind": "book", "year": book.get("firstPublishYear"),
                    "author": next((author["name"] for author in book.get("authors", []) if author.get("name")), "")}
                    for book in matches]
            except BooksError as error:
                raise TorrentError(str(error)) from None
            finally:
                catalogue.downloads.stop()
                catalogue.commands.close()
        if item["kind"] not in ("movie", "tv"):
            return []
        from spaces.movies.backend import Backend

        catalogue = Backend(data=self.data)
        matches = catalogue.browse({"kind": item["kind"], "query": query, "filters": {}})["items"]
        if item["kind"] != "tv":
            return matches
        parsed = item["guess"]
        season, episode = parsed.get("season"), parsed.get("episode")
        if season is None or episode is None:
            return matches
        code = f"S{int(season):02d}E{int(episode):02d}"

        def label(title):
            name = ""
            try:
                page = ""
                for _ in range(10):
                    result = catalogue.episodes({"title": title, "season": season, "page": page})
                    found = next(
                        (
                            row
                            for row in result.get("items", [])
                            if int(row.get("number") or 0) == int(episode)
                        ),
                        None,
                    )
                    if found:
                        name = found.get("title") or ""
                        break
                    page = result.get("next") or ""
                    if not page:
                        break
            except Exception:
                pass
            return title | {"episodeLabel": code + (" · " + name if name else "")}

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(label, matches[:10])) + [
                title | {"episodeLabel": code} for title in matches[10:]
            ]

    def scan_import(self, request):
        token = str(request.get("token") or "")
        item = self.scan_pending.get(token)
        if not item:
            raise TorrentError("Scan this folder again before matching files.")
        title = dict(request.get("title") or {})
        if title.get("kind") != item["kind"] or not title.get("title"):
            raise TorrentError("Choose a matching catalogue item.")
        if item["kind"] == "music" and request.get("releaseDate"):
            title["releaseDate"] = str(request["releaseDate"]).strip()
        try:
            related = {
                key: entry
                for key, entry in self.scan_pending.items()
                if key == token
                or (
                    item["kind"] == "tv"
                    and item["torrent_hash"]
                    and entry["torrent_hash"] == item["torrent_hash"]
                )
            }
            for entry in related.values():
                source = Path(entry["path"])
                stat = source.stat()
                if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != entry["stat"]:
                    raise TorrentError(
                        "A file changed since the scan. Scan it again before importing."
                    )
            identity(title)
            parsed = item["guess"]
            season = request.get("season", parsed.get("season"))
            episode = request.get("episode", parsed.get("episode"))
            if item["torrent_hash"]:
                torrent = self.torrent(item["torrent_hash"])
                if not torrent:
                    raise TorrentError("The source torrent is no longer available.")
                if len(related) > 1 and item["kind"] != "tv":
                    raise TorrentError(
                        "This torrent contains several files that need separate catalogue matches."
                    )
                assignments = []
                for key, entry in related.items():
                    numbers = entry["guess"]
                    chosen_season = season if key == token else numbers.get("season")
                    chosen_episode = episode if key == token else numbers.get("episode")
                    assignments.append(
                        (
                            Path(entry["path"]),
                            title,
                            chosen_season,
                            chosen_episode,
                            item["kind"] == "game",
                        )
                    )
                target = self.import_torrent_files(torrent, assignments)[list(related).index(token)]
            else:
                _, title, _, _, _ = self.episode_assignments(
                    [(Path(item["path"]), title, season, episode, False)]
                )[0]
                target = self.library.add(
                    title,
                    Path(item["path"]),
                    season=season,
                    episode=episode,
                    preserve_name=item["kind"] == "game",
                    move=True,
                    association_videos=item.get("association_videos"),
                )
        except (OSError, ValueError) as error:
            raise TorrentError(str(error)) from None
        for key in related:
            del self.scan_pending[key]
        return {"path": target, "removedTokens": list(related)}

    def delete_local(self, request):
        path = str(request.get("path") or "")
        with self.db() as db:
            rows = [
                dict(kind=kind, path=saved, hash=torrent_hash)
                for kind, saved, torrent_hash in db.execute(
                    "SELECT f.kind,f.path,"
                    "COALESCE(s.torrent_hash,'') "
                    "FROM local_files f LEFT JOIN local_sources s ON s.path=f.path"
                )
            ]
            jobs = [
                dict(id=job_id, save_path=save_path, hash=torrent_hash)
                for job_id, save_path, torrent_hash in db.execute(
                    "SELECT id,save_path,torrent_hash FROM torrent_downloads"
                )
            ]
        selected = next((row for row in rows if row["path"] == path), None)
        if not selected:
            raise TorrentError("The selected file is no longer in Local.")
        nearby = [
            row
            for row in rows
            if row["path"] == path
            or (
                selected["kind"] in ("movie", "tv")
                and row["kind"] == selected["kind"]
                and Path(row["path"]).parent == Path(path).parent
            )
        ]
        needs_qbit = any(row["hash"] for row in nearby)
        torrents = self.qbit().call("torrents/info") if needs_qbit else []
        by_hash = {str(item.get("hash") or ""): item for item in torrents}
        paths = {path}
        hashes = set()
        while True:
            previous = (paths.copy(), hashes.copy())
            hashes.update(row["hash"] for row in rows if row["path"] in paths and row["hash"])
            folders = {
                Path(row["path"]).parent
                for row in rows
                if row["path"] in paths and row["kind"] in ("movie", "tv")
            }
            paths.update(
                row["path"]
                for row in rows
                if row["kind"] in ("movie", "tv") and Path(row["path"]).parent in folders
            )
            paths.update(row["path"] for row in rows if row["hash"] and row["hash"] in hashes)
            if (paths, hashes) == previous:
                break
        related_jobs = {job["id"] for job in jobs if job["hash"] and job["hash"] in hashes}
        if hashes:
            active = sorted(hashes & set(by_hash))
            if active:
                self.qbit().call(
                    "torrents/delete", {"hashes": "|".join(active), "deleteFiles": "true"}
                )
        self.library.remove(sorted(paths))
        if related_jobs:
            with self.db() as db:
                for job_id in related_jobs:
                    db.execute("DELETE FROM torrent_file_matches WHERE job_id=?", (job_id,))
                    db.execute("DELETE FROM torrent_downloads WHERE id=?", (job_id,))
            for job in jobs:
                if job["id"] in related_jobs:
                    self.remove_download_files(job["id"], job["save_path"])
        return {"removed": sorted(paths), "torrent": bool(hashes)}

    def remove_download_files(self, job_id, save_path):
        folder = Path(save_path)
        expected = self.data / "torrents" / job_id
        if folder == expected and folder.is_dir() and not folder.is_symlink():
            shutil.rmtree(folder)
        (self.data / "torrent-locks" / job_id).unlink(missing_ok=True)

    def delete_job(self, request):
        job_id = str(request.get("job_id") or "")
        with self.db() as db:
            job = db.execute(
                "SELECT save_path,torrent_hash FROM torrent_downloads WHERE id=?", (job_id,)
            ).fetchone()
            if not job:
                raise TorrentError("This download is no longer tracked.")
            linked = db.execute(
                "SELECT f.path FROM local_files f JOIN local_sources s ON s.path=f.path "
                "WHERE ?<>'' AND s.torrent_hash=? LIMIT 1",
                (job[1], job[1]),
            ).fetchone()
        if linked:
            return self.delete_local({"path": linked[0]})
        torrents = self.qbit().call("torrents/info")
        torrent = self.find_job_torrent(job_id, job[1], torrents)
        if torrent:
            self.qbit().call("torrents/delete", {"hashes": torrent["hash"], "deleteFiles": "true"})
        with self.db() as db:
            db.execute("DELETE FROM torrent_file_matches WHERE job_id=?", (job_id,))
            db.execute("DELETE FROM torrent_downloads WHERE id=?", (job_id,))
        self.remove_download_files(job_id, job[0])
        folder = Path(job[0])
        if not folder.is_symlink() and any(
            folder.resolve().is_relative_to(library_root(kind).resolve())
            and folder.resolve() != library_root(kind).resolve()
            for kind in ("movie", "tv")
        ):
            try:
                folder.rmdir()  # Another torrent may still use this title directory.
            except OSError:
                pass
        return {"removed": [], "torrent": bool(torrent)}

    def handle(self, request):
        operation = request["op"]
        if operation == "local_list":
            return self.library.list(request["kind"])
        if operation == "local_files":
            return self.library.files(request["title"])
        if operation not in (
            "init",
            "probe",
            "start_qbittorrent",
            "search",
            "results",
            "status",
            "stop",
            "queue",
            "inspect",
            "jobs",
            "review",
            "import_selected",
            "scan",
            "scan_lookup",
            "scan_import",
            "delete_local",
            "delete_job",
        ):
            raise TorrentError("Unknown torrent request.")
        return getattr(self, operation)(request)


def main():
    from spaces.movies.worker import serve, own_process_group

    backend = TorrentBackend()
    own_process_group(backend.shutdown)
    serve(
        backend.handle,
        errors=(TorrentError, ValueError),
        controls=(
            "start_qbittorrent",
            "queue",
            "stop",
            "jobs",
            "import_selected",
            "scan",
            "scan_import",
            "delete_local",
            "delete_job",
        ),
    )


if __name__ == "__main__":
    main()
