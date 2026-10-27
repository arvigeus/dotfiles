"""Radio's portable records, offline catalogue and instance-owned audio player."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spaces.radio import api
from spaces.radio.storage import atomic_json, read_json, http_url
from spaces.radio.favorites import FavoritesStore, configured
from spaces.pictures.mpv import MpvIpc
from spaces.movies.worker import own_process_group, serve

ROOT = 'quickshell/desktop/spaces/radio'


class RadioIpc(MpvIpc):
    def directory(self):
        runtime = Path(os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir())
        path = runtime / ('quickshell-radio-' + str(os.getuid()))
        if len(os.fsencode(str(path / ('mpv-' + 'a' * 16 + '.sock')))) >= 100:
            path = Path(tempfile.gettempdir()) / path.name
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or path.stat().st_uid != os.getuid():
            raise api.RadioError("Radio's player directory is unavailable.")
        path.chmod(0o700)
        return path


def metadata_title(metadata):
    if not isinstance(metadata, dict):
        return ''
    values = {
        re.sub(r'[^a-z0-9]', '', str(key).casefold()): value
        for key, value in metadata.items()
    }

    def first(keys):
        return next(
            (
                str(values[key]).strip()
                for key in keys
                if isinstance(values.get(key), (str, int, float))
                and str(values[key]).strip()
            ),
            '',
        )

    title = first(('icytitle', 'streamtitle', 'nowplaying', 'title', 'song'))
    artist = first(('artist', 'icyartist', 'performer'))
    return (
        artist + ' - ' + title
        if artist and title and artist.casefold() not in title.casefold()
        else title
    )


class RadioBackend:
    def __init__(self, config=None, data=None, cache=None):
        self.config = (
            Path(config)
            if config
            else Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / ROOT
        )
        self.data = (
            Path(data)
            if data
            else Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
            / ROOT
        )
        self.cache = (
            Path(cache)
            if cache
            else Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / ROOT
        )
        self.player = None
        self.station = {}
        self.ipc_path = ''
        self.ipc = RadioIpc('radio', timeout=0.25)

    def init(self):
        self.config.mkdir(parents=True, exist_ok=True, mode=0o700)
        settings_path = self.config / 'radio-ui.json'
        settings = read_json(settings_path, {})
        if not isinstance(settings, dict):
            raise api.RadioError('Radio preferences must be a JSON object.')
        if not settings_path.exists():
            atomic_json(settings_path, settings)
        path = self.data / 'favorites.json'
        favorites = read_json(path, [])
        if not isinstance(favorites, list):
            raise api.RadioError('Radio favorites must be a JSON array.')
        if not path.exists():
            atomic_json(path, favorites)
        return dict(settings=settings, favorites=favorites, syncConfigured=configured())

    def save_settings(self, args):
        settings = args.get('settings')
        if (
            not isinstance(settings, dict)
            or not isinstance(settings.get('genres', []), list)
            or not isinstance(settings.get('qualities', {}), dict)
        ):
            raise api.RadioError('Invalid Radio preferences.')
        atomic_json(
            self.config / 'radio-ui.json',
            {
                'country': str(settings.get('country') or '')[:200],
                'genres': [str(tag)[:100] for tag in settings.get('genres', [])[:12]],
                'qualities': dict(list(settings.get('qualities', {}).items())[:1000]),
            },
        )
        return True

    def save_favorites(self, args):
        return FavoritesStore(self.data).save(args.get('favorites'))

    def cached(self, op, args):
        key = hashlib.sha256(
            json.dumps([op, args], sort_keys=True).encode()
        ).hexdigest()
        path = self.cache / (key + '.json')
        try:
            if op == 'browse':
                with api.browse_lock:
                    result = api.browse(args)
            else:
                if op == 'countries':
                    result = {'items': api.list_countries()}
                else:
                    with api.browse_lock:
                        result = {'items': api.list_genres()}
            try:
                atomic_json(path, result)
            except OSError:
                pass  # A full cache volume must not discard a valid network response.
            return result
        except api.RadioError:
            result = read_json(path, None)
            if not isinstance(result, dict):
                raise
            result = dict(result, warning='Offline: showing saved stations.')
            if op == 'browse':
                result[
                    'nextOffset'
                ] = -1  # Genre cursors belong to the live worker session.
            return result

    def resolve(self, args):
        station = api.station_record(args.get('station'))
        if not station:
            raise api.RadioError('Select a station first.')
        if station.get('source') == 'nextcloud':
            url = http_url(station['url_resolved']) or http_url(station['url'])
            if not url:
                raise api.RadioError('This saved station has no playable HTTP stream.')
            return dict(station=station, url=url, warning='')
        try:
            identity = str(uuid.UUID(station['stationuuid']))
        except ValueError:
            raise api.RadioError('This station has an invalid ID.') from None
        warning = ''
        try:
            result = api.api_get('/json/url/' + quote(identity, safe=''))
            url = http_url(result.get('url')) if isinstance(result, dict) else ''
        except api.RadioError:
            url = http_url(station['url_resolved']) or http_url(station['url'])
            warning = (
                'The station directory is unavailable; trying the saved stream address.'
            )
        if not url:
            raise api.RadioError('This station has no playable HTTP stream.')
        return dict(station=station, url=url, warning=warning)

    def start(self, args):
        mpv = shutil.which('mpv')
        if not mpv:
            raise api.RadioError('Install mpv to play Radio streams.')
        url = http_url(args.get('url'))
        station = api.station_record(args.get('station'))
        if not url or not station:
            raise api.RadioError('This station has no playable HTTP stream.')
        self.stop()
        self.ipc_path = str(
            self.ipc.directory() / ('mpv-' + uuid.uuid4().hex[:16] + '.sock')
        )
        try:
            self.player = subprocess.Popen(
                [
                    mpv,
                    '--no-config',
                    '--no-video',
                    '--no-terminal',
                    '--really-quiet',
                    '--input-ipc-server=' + self.ipc_path,
                    '--script=/usr/lib/mpv-mpris/mpris.so',
                    '--audio-client-name=Radio',
                    '--',
                    url,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self.ipc.cleanup(self.ipc_path)
            self.ipc_path = ''
            raise api.RadioError('Radio could not start mpv.') from None
        self.station = station
        return dict(
            playing=True, station=station, title='', paused=False, connecting=True
        )

    def stop(self):
        if self.player:
            if self.player.poll() is None:
                self.player.terminate()
                try:
                    self.player.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    self.player.kill()
                    self.player.wait(timeout=0.5)
            self.player = None
        if self.ipc_path:
            self.ipc.cleanup(self.ipc_path)
        self.ipc_path = ''
        self.station = {}
        return dict(playing=False, station={}, title='', paused=False)

    def status(self):
        if not self.player:
            return dict(playing=False, station={}, title='', paused=False)
        code = self.player.poll()
        if code is not None:
            result = self.stop()
            result['error'] = (
                'The stream ended or could not be played.'
                if code
                else 'Playback ended.'
            )
            return result
        title = metadata_title(self.ipc.property(self.ipc_path, 'metadata'))
        if not title:
            title = str(self.ipc.property(self.ipc_path, 'media-title') or '')
        if title.casefold() == self.station.get('name', '').casefold() or http_url(
            title
        ):
            title = ''
        paused = self.ipc.property(self.ipc_path, 'pause')
        return dict(
            playing=True,
            station=self.station,
            title=title,
            paused=bool(paused),
            connecting=paused is None
            or bool(self.ipc.property(self.ipc_path, 'core-idle')),
        )

    def handle(self, request):
        op = request['op']
        if op == 'init':
            return self.init()
        if op == 'settings-save':
            return self.save_settings(request)
        if op == 'favorites-save':
            return self.save_favorites(request)
        if op in ('browse', 'countries', 'genres'):
            args = {
                key: value for key, value in request.items() if key not in ('id', 'op')
            }
            return self.cached(op, args)
        if op == 'resolve':
            return self.resolve(request)
        if op == 'start':
            return self.start(request)
        if op == 'stop':
            return self.stop()
        if op == 'status':
            return self.status()
        if op == 'pause':
            if not self.ipc.send(self.ipc_path, ['cycle', 'pause']):
                raise api.RadioError(
                    'The player is still connecting. Try again shortly.'
                )
            return self.status()
        raise api.RadioError('Unknown Radio operation.')


def main():
    backend = RadioBackend()
    own_process_group(backend.stop)
    try:
        serve(
            backend.handle,
            errors=(api.RadioError, OSError, ValueError),
            latest=('browse', 'resolve'),
            controls=(
                'init',
                'settings-save',
                'favorites-save',
                'start',
                'stop',
                'status',
                'pause',
            ),
        )
    finally:
        backend.stop()


if __name__ == '__main__':
    main()
