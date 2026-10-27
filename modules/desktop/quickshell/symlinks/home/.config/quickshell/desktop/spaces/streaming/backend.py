"""Streaming catalogue, portable library, background transfers and video insights."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spaces.books.jobs import Jobs
from spaces.movies.worker import own_process_group, serve
from spaces.streaming import insights
from spaces.streaming.downloads import download
from spaces.streaming.player import Player
from spaces.streaming.posts import PostsClient
from spaces.streaming.storage import Library, StreamingError, atomic_json, read_json
from spaces.streaming.youtube import (
    Commands,
    access_error,
    channel_id,
    channel_url,
    members_only,
    record,
    video_id,
)

ROOT = 'quickshell/desktop/spaces/streaming'
PAGE_SIZE = 24


class StreamingBackend:
    def __init__(self, config=None, data=None, cache=None, music=None, videos=None):
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
        self.music = Path(music) if music else Path.home() / 'Music'
        self.videos = Path(videos) if videos else Path.home() / 'Videos' / 'Streaming'
        self.library = Library(self.data)
        self.commands = Commands()
        self.player = Player(self.data)
        self.jobs = Jobs(errors=(StreamingError, OSError))
        self.lock = threading.RLock()
        self.details_cache = {}
        self.catalogue_cache = {}
        self.posts = PostsClient(self.cache / 'posts')

    def settings(self):
        value = read_json(self.config / 'streaming.json', {})
        if not isinstance(value, dict):
            raise StreamingError('streaming.json must contain an object.')
        channels = value.get('channels', [])
        model = value.get('gemini_model', insights.DEFAULT_MODEL)
        grid_mode = value.get('grid_mode', False)
        if type(grid_mode) is not bool:
            raise StreamingError('Invalid Streaming layout preference.')
        if (
            not isinstance(channels, list)
            or len(channels) > 40
            or not isinstance(model, str)
        ):
            raise StreamingError(
                'Invalid Streaming settings. Use up to 40 channels and a Gemini model name.'
            )
        channels = [
            dict(
                url=channel_url(c['url']),
                name=str(c.get('name') or c['url'])[:500],
                id=channel_id(c.get('id')) or channel_id(c['url']),
                aliases=list(
                    dict.fromkeys(
                        channel_url(alias) for alias in c.get('aliases', [])[:10]
                    )
                ),
            )
            for c in channels
            if isinstance(c, dict)
            and isinstance(c.get('url'), str)
            and isinstance(c.get('aliases', []), list)
        ]
        if len(channels) != len(value.get('channels', [])):
            raise StreamingError('A saved Streaming channel is invalid.')
        return dict(channels=channels, gemini_model=model, grid_mode=grid_mode)

    def update_settings(self, action):
        with self.lock:
            settings = self.settings()
            action(settings)
            atomic_json(self.config / 'streaming.json', settings)
            return settings

    def remember_channel(self, source, identity, name='', aliases=()):
        identity = channel_id(identity)
        if not identity:
            return
        with self.lock:
            settings = self.settings()
            channel = next(
                (c for c in settings['channels'] if c['url'] == source), None
            )
            if not channel:
                return
            previous = dict(channel)
            channel['id'] = identity
            if name:
                channel['name'] = name[:500]
            valid = [channel['url'], 'https://www.youtube.com/channel/' + identity]
            for value in aliases:
                try:
                    valid.append(channel_url(value))
                except StreamingError:
                    pass
            channel['aliases'] = list(dict.fromkeys([*channel['aliases'], *valid]))[:10]
            if channel != previous:
                atomic_json(self.config / 'streaming.json', settings)

    @property
    def key_path(self):
        return self.config.parent.parent / 'integrations/gemini-api-key'

    def init(self):
        settings = self.settings()
        state = self.library.read()
        if not (self.config / 'streaming.json').exists():
            atomic_json(self.config / 'streaming.json', settings)
        if not self.library.path.exists():
            atomic_json(self.library.path, state)
        resume = self.data / 'resume'
        resume.mkdir(parents=True, exist_ok=True, mode=0o700)
        resume.chmod(0o700)
        return dict(settings=settings, gemini=self.key_path.is_file())

    def browse(self, request):
        result = self.cached_browse(request)
        # Hash before membership filtering: different hidden-only pages still
        # advance, whereas a provider replay must stop automatic pagination.
        key = (
            result.get('pageKey')
            or hashlib.sha256(
                json.dumps(sorted(item['id'] for item in result['items'])).encode()
            ).hexdigest()
        )
        with self.lock:
            if request.get('tab') != 'posts':
                result = dict(
                    result,
                    items=[
                        item
                        for item in result['items']
                        if not members_only(item)
                        and not members_only(self.details_cache.get(item['id'], {}))
                    ],
                )
                for item in result['items']:
                    self.catalogue_cache[item['id']] = item
            while len(self.catalogue_cache) > 1000:
                self.catalogue_cache.pop(next(iter(self.catalogue_cache)))
        return dict(result, channels=self.settings()['channels'], pageKey=key)

    def cached_browse(self, request):
        if request.get('tab', 'feed') not in ('feed', 'search', 'posts'):
            return self._browse(request)
        scope = {k: request.get(k) for k in ('tab', 'page', 'query', 'channel')}
        scope['channels'] = [channel['url'] for channel in self.settings()['channels']]
        scope['version'] = 3 if request.get('tab') == 'posts' else 2
        name = (
            hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
            + '.json'
        )
        path = self.cache / name
        try:
            cached = read_json(path, None)
            if cached and (
                not isinstance(cached, dict)
                or not isinstance(cached.get('items'), list)
            ):
                cached = None
        except StreamingError:
            cached = None
        if (
            cached
            and not request.get('refresh')
            and time.time() - path.stat().st_mtime < 300
        ):
            return cached
        try:
            result = self._browse(request)
        except StreamingError:
            if cached:
                return dict(
                    cached,
                    more=False,
                    warning='Offline snapshot. Refresh to try YouTube again.',
                )
            raise
        atomic_json(path, result)
        files = sorted(
            self.cache.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for old in files[200:]:
            old.unlink(missing_ok=True)
        return result

    def _browse(self, request):
        tab = request.get('tab', 'feed')
        page = request.get('page', 0)
        if type(page) is not int or not 0 <= page < 2**31:
            raise StreamingError('Invalid video page.')
        query = str(request.get('query') or '').strip()[:300]
        if tab == 'posts':
            return self.browse_posts(request)
        if tab == 'search':
            if not query:
                return dict(items=[], more=False)
            if query.startswith(('https://', 'http://')):
                identity = video_id(query)
                try:
                    return dict(items=[self.details(identity)], more=False)
                except StreamingError as error:
                    return dict(
                        items=[self.known(identity)],
                        more=False,
                        warning='Video details are unavailable. ' + str(error),
                    )
            raw = self.commands.extract(
                'ytsearch' + str((page + 1) * PAGE_SIZE) + ':' + query,
                flat=True,
                start=page * PAGE_SIZE + 1,
                count=PAGE_SIZE,
            )
            rows = [
                item
                for raw_item in raw.get('entries', [])
                if isinstance(raw_item, dict) and (item := record(raw_item))
            ]
            return dict(items=rows, more=len(rows) == PAGE_SIZE)
        if tab != 'feed':
            raise StreamingError('Unknown Streaming view.')
        channels = self.settings()['channels']
        selected = request.get('channel', '')
        if selected:
            channels = [c for c in channels if c['url'] == selected]
        if not channels:
            return dict(items=[], more=False)

        def fetch(channel):
            raw = self.commands.extract(
                channel['url'] + '/videos', flat=True, start=page * 12 + 1, count=12
            )
            identity = channel_id(raw.get('channel_id')) or channel_id(raw.get('id'))
            self.remember_channel(
                channel['url'],
                identity,
                str(raw.get('channel') or raw.get('uploader') or ''),
                (raw.get('uploader_url'), raw.get('channel_url')),
            )
            items = [
                item
                for r in raw.get('entries', [])
                if isinstance(r, dict) and (item := record(r))
            ]
            for item in items:
                item['creator'] = item['creator'] or str(
                    raw.get('channel') or raw.get('uploader') or channel['name']
                )
                item['channel'] = item['channel'] or channel['url']
                item['channelId'] = item['channelId'] or identity
                item['followedChannelUrl'] = channel['url']
            return items

        rows, failed, more = [], 0, False
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(fetch, c) for c in channels]
            for future in futures:
                try:
                    items = future.result()
                    more |= len(items) == 12
                    rows.extend(items)
                except StreamingError:
                    failed += 1
        if failed == len(channels):
            raise StreamingError(
                'Your channel feed could not be loaded. Check your connection and update yt-dlp.'
            )
        rows = list({r['id']: r for r in rows}.values())
        rows.sort(key=lambda r: r['date'], reverse=True)
        if query:
            rows = [
                r
                for r in rows
                if query.casefold() in (r['title'] + ' ' + r['creator']).casefold()
            ]
        return dict(
            items=rows,
            more=more,
            warning=f'{failed} channel(s) could not be loaded.' if failed else '',
        )

    def browse_posts(self, request):
        channels = self.settings()['channels']
        if request.get('channel'):
            channels = [c for c in channels if c['url'] == request['channel']]
        rows, failed, more, keys = [], 0, False, []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                (c, pool.submit(self.posts.page, c, request.get('page', 0)))
                for c in channels
            ]
            for channel, future in futures:
                try:
                    result = future.result()
                    rows.extend(result['items'])
                    more |= result['more']
                    keys.append(
                        (
                            channel['url'],
                            result.get('pageKey')
                            or sorted(row['id'] for row in result['items']),
                        )
                    )
                    if result['items']:
                        first = result['items'][0]
                        self.remember_channel(
                            channel['url'],
                            first.get('channelId'),
                            first.get('creator', ''),
                        )
                except StreamingError:
                    failed += 1
        if channels and failed == len(channels):
            raise StreamingError(
                "Your creators' Posts could not be loaded. Try Refresh later."
            )
        query = str(request.get('query') or '').strip().casefold()[:300]
        rows = [
            r
            for r in {r['id']: r for r in rows}.values()
            if not query or query in (r['text'] + ' ' + r['creator']).casefold()
        ]
        rows.sort(key=lambda row: row['timestamp'], reverse=True)
        key = hashlib.sha256(json.dumps(sorted(keys)).encode()).hexdigest()
        return dict(
            items=rows,
            more=more,
            pageKey=key,
            warning=f'{failed} creator(s) could not be loaded.' if failed else '',
        )

    def details(self, identity):
        identity = video_id(identity)
        with self.lock:
            item = self.details_cache.get(identity)
        if item:
            return item
        item = self.commands.details(identity)
        with self.lock:
            source = self.catalogue_cache.get(identity, {}).get('followedChannelUrl')
            if source:
                item['followedChannelUrl'] = source
                self.remember_channel(
                    source,
                    item.get('channelId'),
                    item.get('creator', ''),
                    (item.get('channel'),),
                )
            if len(self.details_cache) >= 300:
                self.details_cache.pop(next(iter(self.details_cache)))
            self.details_cache[identity] = item
        return item

    def known(self, identity):
        identity = video_id(identity)
        state = self.library.read()
        with self.lock:
            item = self.details_cache.get(identity)
        if item:
            return item
        for row in state['downloads'].values():
            if row['video']['id'] == identity:
                return row['video']
        with self.lock:
            return self.catalogue_cache.get(identity) or record(dict(id=identity))

    def start_download(self, request):
        identity = video_id(request.get('videoId'))
        audio = request.get('audio', False)
        if type(audio) is not bool:
            raise StreamingError('Invalid download type.')

        def action():
            item = self.details(identity)
            if message := access_error(item.get('availability')):
                raise StreamingError(message)
            if item['live'] or item.get('upcoming'):
                raise StreamingError(
                    'Wait for the live video to finish before downloading it.'
                )
            result = download(
                self.commands, item, self.music if audio else self.videos, audio
            )
            self.library.put(
                'downloads', identity + (':audio' if audio else ':video'), result
            )
            return dict(kind='download', videoId=identity, **result)

        return self.jobs.start('Download audio' if audio else 'Download video', action)

    def analyze(self, request):
        identity = video_id(request.get('videoId'))
        if message := access_error(self.known(identity).get('availability')):
            raise StreamingError(message)
        question = request.get('question', '')
        if not isinstance(question, str) or len(question) > 2000:
            raise StreamingError('Use a question of at most 2,000 characters.')
        question = question.strip()
        model = self.settings()['gemini_model']
        cache_key = hashlib.sha256(
            (identity + '\0' + model + '\0' + question).encode()
        ).hexdigest()

        def action():
            cached = self.library.read()['summaries'].get(cache_key)
            answer = (
                cached['text']
                if cached
                else insights.generate(identity, self.key_path, model, question)
            )
            if not cached:
                self.library.put(
                    'summaries',
                    cache_key,
                    dict(text=answer, videoId=identity, question=question),
                )
            return dict(
                kind='analysis', videoId=identity, text=answer, question=question
            )

        return self.jobs.start(
            'Video question' if question else 'Video summary', action
        )

    def handle(self, request):
        op = request['op']
        if op == 'init':
            return self.init()
        if op == 'browse':
            return self.browse(request)
        if op == 'details':
            identity = video_id(request.get('videoId'))
            # Offline collections remain useful without a metadata request.
            return (
                self.known(identity)
                if request.get('offline')
                else self.details(identity)
            )
        if op == 'subscribe':
            url = channel_url(request.get('url'))
            identity = channel_id(request.get('channelId')) or channel_id(url)

            def subscribe(settings):
                channels = settings['channels']
                if not any(
                    c['url'].casefold() == url.casefold()
                    or url in c['aliases']
                    or (identity and c['id'] == identity)
                    for c in channels
                ):
                    if len(channels) >= 40:
                        raise StreamingError(
                            'Streaming supports up to 40 followed channels.'
                        )
                    channels.append(
                        dict(
                            url=url,
                            name=str(request.get('name') or url.rsplit('/', 1)[-1])[
                                :500
                            ],
                            id=identity,
                            aliases=[url],
                        )
                    )

            return self.update_settings(subscribe)
        if op == 'unsubscribe':

            def unsubscribe(settings):
                url = request.get('url')
                settings['channels'] = [
                    c
                    for c in settings['channels']
                    if c['url'] != url and url not in c['aliases']
                ]

            return self.update_settings(unsubscribe)
        if op == 'layout':
            if type(request.get('grid_mode')) is not bool:
                raise StreamingError('Invalid layout preference.')
            return self.update_settings(
                lambda settings: settings.update(grid_mode=request['grid_mode'])
            )
        if op == 'play':
            identity = video_id(request.get('videoId'))
            item = self.known(identity)
            audio = request.get('audio', False) is True
            downloads = self.library.read()['downloads']
            local = downloads.get(identity + (':audio' if audio else ':video'), {}).get(
                'path', ''
            )
            if local and not Path(local).is_file():
                local = ''
            if request.get('offline') and not local:
                raise StreamingError(
                    'The downloaded file is missing. Download it again to watch offline.'
                )
            if not local and (message := access_error(item.get('availability'))):
                raise StreamingError(message)
            return self.player.start(item, local, audio, request.get('start'))
        if op == 'pause':
            return self.player.pause()
        if op == 'stop':
            return self.player.stop()
        if op == 'status':
            return self.player.status()
        if op == 'download':
            return self.start_download(request)
        if op == 'analyze':
            return self.analyze(request)
        if op == 'jobs':
            return self.jobs.snapshots()
        if op == 'cancel':
            return self.jobs.cancel(request.get('job_id'))
        raise StreamingError('Unknown Streaming request.')

    def close(self):
        self.jobs.stop()
        self.commands.close()
        self.player.stop()


if __name__ == '__main__':
    os.umask(0o077)
    backend = StreamingBackend()
    own_process_group(backend.close)
    try:
        serve(
            backend.handle,
            errors=(StreamingError,),
            latest=('browse', 'details'),
            controls=(
                'subscribe',
                'unsubscribe',
                'layout',
                'play',
                'pause',
                'stop',
                'status',
                'download',
                'analyze',
                'cancel',
            ),
        )
    finally:
        backend.close()
