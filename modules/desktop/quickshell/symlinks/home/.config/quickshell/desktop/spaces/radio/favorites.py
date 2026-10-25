"""Local-first favorites and serialized two-way Nextcloud Music membership sync."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from integrations import nextcloud
from spaces.radio import api
from spaces.radio.music import MusicClient, MusicError
from spaces.radio.matching import RadioMatcher
from spaces.radio.storage import atomic_json, read_json, http_url
from spaces.movies.worker import own_process_group, serve


def configured():
    return (nextcloud.config_root() / "nextcloud.json").is_file() and (nextcloud.config_root() / "nextcloud-music-api-key").is_file()


def variants(record):
    return record.get("variants") or [record]


def identities(record):
    return {str(item.get("stationuuid", "")) for item in [record, *variants(record)]}


def url_key(url):
    parsed = urlsplit(http_url(url))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, "")) if parsed.netloc else ""


def urls(record):
    return {key for item in [record, *variants(record)] for value in (item.get("url"), item.get("url_resolved")) if (key := url_key(value))}


def projection(record):
    stream = http_url(record.get("url_resolved")) or http_url(record.get("url"))
    if not stream:
        raise MusicError("A favorite has no HTTP stream to save to Nextcloud Music. It remains saved locally.")
    return dict(name=record["name"], streamUrl=stream, homepageUrl=http_url(record.get("homepage")))


def clean_favorites(values):
    if not isinstance(values, list) or len(values) > 1000:
        raise api.RadioError("Radio supports up to 1,000 favorite stations.")
    favorites = []
    for raw in values:
        record = api.station_record(raw)
        if not record or not isinstance(raw.get("variants", []), list):
            raise api.RadioError("A favorite station is invalid; saved favorites were preserved.")
        record["variants"] = [item for value in variants(raw)[:100] if (item := api.station_record(value))]
        favorites.append(record)
    return favorites


def import_station(remote, account_id):
    identity = str(uuid.uuid5(uuid.NAMESPACE_URL, account_id + ":radio:" + str(remote["id"])))
    record = api.station_record(dict(stationuuid=identity, name=remote.get("name") or remote["streamUrl"],
                                    url=remote["streamUrl"], url_resolved=remote["streamUrl"],
                                    homepage=remote.get("homePageUrl", ""), source="nextcloud"))
    return dict(record, variants=[dict(record)])


def apply_remote(record, remote):
    """Keep provider metadata/IDs and alternate qualities when the stream still matches."""
    result = dict(record)
    name = remote.get("name") or remote["streamUrl"]
    if url_key(remote["streamUrl"]) not in urls(record):
        result.update(url=remote["streamUrl"], url_resolved=remote["streamUrl"], source="nextcloud", codec="", bitrate=0)
        result["variants"] = [dict(result, variants=[])]
    result["name"] = name
    # Older Music versions omit homePageUrl; absence must not erase local metadata.
    if "homePageUrl" in remote:
        result["homepage"] = remote.get("homePageUrl") or ""
    result["variants"] = [dict(item, name=name, **({"homepage": result["homepage"]} if "homePageUrl" in remote else {})) for item in variants(result)]
    return result


class FavoritesStore:
    def __init__(self, data=None, client_factory=MusicClient, matcher=None):
        self.data = Path(data) if data else Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "quickshell/desktop/spaces/radio"
        self.path = self.data / "favorites.json"
        self.state_path = self.data / "sync.json"
        self.client_factory = client_factory
        self.matcher = matcher if matcher is not None else RadioMatcher() if client_factory is MusicClient else None

    @contextmanager
    def locked(self):
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.data / ".favorites.lock").open("a") as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self):
        return clean_favorites(read_json(self.path, []))

    def save(self, values):
        records = clean_favorites(values)
        with self.locked():
            atomic_json(self.path, records)
        return records

    def sync(self):
        # This worker owns only favorites. A slow cloud cannot block audio controls.
        with self.locked():
            if self.state_path.exists() and not self.path.is_file():
                raise MusicError("Local favorites are missing; cloud stations were preserved. Restore favorites.json before syncing.")
            local = self.read()
            if not configured() and self.client_factory is MusicClient:
                return dict(favorites=local, configured=False, warning="")
            client = self.client_factory()
            state = read_json(self.state_path, {"account": client.account_id, "links": {}, "pending": {}})
            if (not isinstance(state, dict) or not isinstance(state.get("links"), dict)
                    or not isinstance(state.get("pending"), dict)
                    or any(not isinstance(key, str) or not key.isdigit() or not isinstance(value, str) or not value for key, value in state.get("links", {}).items())
                    or any(not isinstance(value, dict) or not http_url(value.get("streamUrl")) for value in state.get("pending", {}).values())):
                raise MusicError("Radio's sync records are invalid; local and cloud favorites were preserved.")
            if state.get("account") != client.account_id:
                raise MusicError("The shared Nextcloud account changed. Radio's previous sync records were preserved; reconcile them before syncing another account.")
            remote = {str(row["id"]): row for row in client.stations()}
            if any(not http_url(row["streamUrl"]) for row in remote.values()):
                raise MusicError("Nextcloud Music contains a non-HTTP station. Favorites were preserved; update that stream before syncing.")
            links = state["links"]
            pending = state["pending"]
            matches = state.setdefault("matches", {})
            if not isinstance(matches, dict):
                raise MusicError("Radio's saved station matches are invalid; favorites were preserved.")
            match_warning = ""
            def checkpoint():
                atomic_json(self.state_path, state)
            def find_local(identity):
                return next((item for item in local if identity in identities(item)), None)
            def find_url(stream):
                return next((item for item in local if url_key(stream) in urls(item)), None)
            def catalogue_record(item, remote_id, row):
                nonlocal match_warning
                if self.matcher is None:
                    return item
                saved = matches.get(remote_id, {})
                preferred = saved.get("uuid") if saved.get("stream") == row["streamUrl"] else None
                if not preferred and not item.get("source") and url_key(row["streamUrl"]) in urls(item):
                    preferred = item["stationuuid"]
                try:
                    record = self.matcher.match(row, preferred)
                except (api.RadioError, OSError, ValueError):
                    match_warning = "Some station details could not be matched. Favorites are saved; retry sync to refresh them."
                    return item
                if not record:
                    return item
                desired = projection(record)
                if row.get("name") != desired["name"] or url_key(row["streamUrl"]) != url_key(desired["streamUrl"]) or ("homePageUrl" in row and (row.get("homePageUrl") or "") != desired["homepageUrl"]):
                    # Subsonic has no conditional update. Re-read before changing a
                    # known ID rather than overwriting an already-observed cloud edit.
                    latest = next((value for value in client.stations() if str(value["id"]) == remote_id), None)
                    if latest != row:
                        raise MusicError("A station changed on Nextcloud Music during matching. Retry sync to reconcile it.")
                    client.request("updateInternetRadioStation", id=remote_id, **desired)
                    actual = next((value for value in client.stations() if str(value["id"]) == remote_id), None)
                    if actual is None or actual.get("name") != desired["name"] or url_key(actual["streamUrl"]) != url_key(desired["streamUrl"]):
                        raise MusicError("The corrected station could not be verified on Nextcloud Music. Retry sync.")
                    remote[remote_id] = actual
                matches[remote_id] = dict(uuid=record["stationuuid"], stream=remote[remote_id]["streamUrl"])
                return record

            # Recover uncertain creates by reading the server before considering a retry.
            # Pending intent also remembers an unstar made after a lost create response.
            for identity, entry in list(pending.items()):
                found = next((key for key, row in remote.items() if url_key(row["streamUrl"]) == url_key(entry["streamUrl"])), None)
                if found is not None:
                    links[found] = identity
                    del pending[identity]
                    checkpoint()

            # Known IDs distinguish actual unstars from the first empty local install.
            removed_remote = set()
            for remote_id, identity in list(links.items()):
                item = find_local(identity)
                if item is None and remote_id in remote:
                    # Re-associate a catalogue record replacing a cloud-only import.
                    item = find_url(remote[remote_id]["streamUrl"])
                    if item:
                        links[remote_id] = item["stationuuid"]
                if item is None:
                    if remote_id in remote:
                        client.request("deleteInternetRadioStation", id=remote_id)
                        del remote[remote_id]
                    del links[remote_id]
                    checkpoint()
                elif remote_id not in remote:
                    removed_remote.add(remote_id)

            # Remote removal wins membership, unless another server entry still owns
            # the same grouped local station. Do not recreate deleted server rows.
            remove_local = set()
            for remote_id in removed_remote:
                item = find_local(links[remote_id])
                if item and not any(key in remote and value in identities(item) for key, value in links.items()):
                    remove_local.add(item["stationuuid"])
            remaining = [item for item in local if item["stationuuid"] not in remove_local]

            # Match pre-existing stations by stream URL, never by a fuzzy station name.
            for remote_id, row in remote.items():
                if remote_id not in links:
                    item = find_url(row["streamUrl"])
                    if item and item in remaining:
                        links[remote_id] = item["stationuuid"]
                        checkpoint()

            for item in remaining:
                if any(value in identities(item) and key in remote for key, value in links.items()):
                    continue
                entry = projection(item)
                identity = item["stationuuid"]
                pending[identity] = entry
                checkpoint()  # Durable before POST, including timeout/close uncertainty.
                client.request("createInternetRadioStation", **entry)
                after = {str(row["id"]): row for row in client.stations()}
                created_ids = [key for key, row in after.items() if url_key(row["streamUrl"]) == url_key(entry["streamUrl"])]
                if not created_ids:
                    raise MusicError("Nextcloud Music accepted a station but readback is pending. Its local favorite is preserved.")
                links[created_ids[0]] = identity
                del pending[identity]
                remote = after
                checkpoint()

            # All remote-only records are appended only after mutations finish. Their
            # links are committed after favorites, so an interrupted import cannot
            # be mistaken for an explicit local removal on the next attempt.
            result = []
            final_links = {key: value for key, value in links.items() if key in remote}
            for item in remaining:
                remote_id = next((key for key in remote if final_links.get(key) in identities(item)), None)
                matched = remote.get(remote_id)
                updated = apply_remote(item, matched) if matched else item
                result.append(catalogue_record(updated, remote_id, matched) if matched else updated)
                for key, identity in list(final_links.items()):
                    if identity in identities(item):
                        final_links[key] = result[-1]["stationuuid"]
            for remote_id, row in remote.items():
                if remote_id not in final_links:
                    item = import_station(row, client.account_id)
                    item = catalogue_record(item, remote_id, row)
                    result.append(item)
                    final_links[remote_id] = item["stationuuid"]
            if len(result) > 1000:
                raise MusicError("The combined favorites exceed 1,000 stations. Local favorites were preserved.")
            result = clean_favorites(result)
            atomic_json(self.path, result)
            state["links"] = final_links
            state["matches"] = {key: value for key, value in matches.items() if key in remote}
            state["synced"] = int(time.time())
            checkpoint()
            return dict(favorites=result, configured=True, synced=state["synced"], warning=match_warning)

    def handle(self, request):
        if request["op"] == "favorites-save":
            return self.save(request.get("favorites"))
        if request["op"] == "sync":
            return self.sync()
        raise api.RadioError("Unknown Radio favorites operation.")


def main():
    store = FavoritesStore()
    own_process_group()
    serve(store.handle, errors=(api.RadioError, MusicError, nextcloud.NextcloudError, OSError),
          controls=("favorites-save", "sync"))


if __name__ == "__main__":
    main()
