"""Nextcloud library records, account isolation, offline views and credential-free streams."""

import io
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError
from urllib.parse import parse_qs
from urllib.request import urlopen
from unittest.mock import MagicMock, patch
import sys
import support

sys.path.insert(0, str(support.DESKTOP))
from integrations.subsonic import MusicError
from spaces.music.cloud import CloudLibrary, LibraryClient, record
from spaces.music.cloud_stream import StreamBroker


class Client:
    account_id = 'fixture-account'

    def __init__(self):
        self.calls = []
        self.offline = False

    def request(self, method, **args):
        self.calls.append((method, args))
        if self.offline:
            raise MusicError('Offline')
        song = dict(
            id='s1',
            title='Song',
            artist='Artist',
            album='Album',
            albumId='b1',
            artistId='a1',
            genre='Rock',
            duration=123,
            path='/album/song.flac',
            playCount=17,
        )
        album = dict(id='b1', name='Album', artist='Artist', artistId='a1', song=[song])
        artist = dict(
            id='a1',
            name='Artist',
            album=[dict(album, id='b' + str(i)) for i in range(5)],
        )
        return {
            'search3': {'searchResult3': {'song': [song]}},
            'getArtists': {'artists': {'index': [{'artist': [artist]}]}},
            'getAlbumList2': {'albumList2': {'album': [album]}},
            'getAlbum': {'album': dict(album, id=args.get('id', 'b1'))},
            'getSong': {'song': song},
            'getArtist': {'artist': artist},
            'getGenres': {'genres': {'genre': [{'value': 'Rock'}]}},
            'getSongsByGenre': {'songsByGenre': {'song': [song]}},
        }[method]


class CloudLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = Client()
        self.library = CloudLibrary(self.client, Path(self.tmp.name) / 'cache')
        self.library.index.start = lambda *args: None

    def test_server_artist_images_reach_qml_only_as_cached_files(self):
        from functools import partial
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import threading

        root = Path(self.tmp.name) / 'server'
        root.mkdir()
        (root / 'artist.png').write_bytes(b'\x89PNG fixture')

        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=root))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}/'
        self.client.account = {'url': origin}
        artist = dict(
            id='a1', kind='artist', source='nextcloud', account=self.client.account_id
        )
        signed = origin + 'artist.png?token=secret'
        with patch.object(
            self.client,
            'request',
            return_value={'artistInfo2': {'biography': 'Bio', 'largeImageUrl': signed}},
        ):
            cover = self.library.artist_info(artist)['artist']['cover']
            self.assertTrue(cover.startswith('file://') and 'secret' not in cover)
            self.assertEqual(Path(cover[7:]).read_bytes(), b'\x89PNG fixture')
        with patch.object(
            self.client,
            'request',
            return_value={
                'artistInfo2': {'largeImageUrl': 'https://elsewhere.example/a.png'}
            },
        ):
            other = dict(artist, id='a2')
            self.assertEqual(self.library.artist_info(other)['artist']['cover'], '')

    def test_response_cache_pruning_tolerates_concurrently_removed_files(self):
        real = Path.glob
        vanished = self.library.cache / 'vanished.json'

        def glob(path, pattern):
            # Another worker removed this entry between listing and stat().
            return iter([vanished, *real(path, pattern)])

        with patch.object(Path, 'glob', glob):
            result = self.library.request('getSong', refresh=True, id='s1')
        self.assertEqual(result['song']['id'], 's1')

    def test_song_play_count_preserves_zero_and_missing_values(self):
        for value in (None, 0, 17, 3_000_000_000):
            with self.subTest(value=value):
                raw = dict(id='s1', playCount=value)
                self.assertEqual(record(raw, 'song', 'fixture')['playCount'], value)
        self.assertIsNone(record(dict(id='s1'), 'song', 'fixture')['playCount'])

    def test_song_information_refreshes_server_play_count(self):
        from spaces.music import local_files

        song = dict(id='s1', account=self.client.account_id)
        with patch.object(local_files, 'DATA', Path(self.tmp.name) / 'data'):
            self.assertEqual(self.library.song_info(song)['song']['playCount'], 17)
            self.client.calls.clear()
            self.assertEqual(self.library.song_info(song)['song']['playCount'], 17)
        self.assertEqual(self.client.calls, [('getSong', {'id': 's1'})])

    def test_library_search_categories_and_genres_are_source_scoped(self):
        songs = self.library.browse({'category': 'songs', 'query': 'Song'})['items']
        self.assertEqual(songs[0]['source'], 'nextcloud')
        self.assertEqual(songs[0]['account'], self.client.account_id)
        self.assertEqual(songs[0]['albumId'], 'b1')
        self.assertEqual(songs[0]['artistIds'], ['a1'])
        self.assertEqual(
            self.client.calls[-1][1],
            dict(query='Song', artistCount=0, albumCount=0, songCount=50, songOffset=0),
        )
        self.assertEqual(
            self.library.browse({'category': 'albums'})['items'][0]['kind'], 'album'
        )
        self.assertEqual(
            self.library.browse({'category': 'artists'})['items'][0]['kind'], 'artist'
        )
        self.assertEqual(self.library.genres(), [dict(id='Rock', name='Rock')])
        self.assertEqual(len(self.library.browse({'genreName': 'Rock'})['items']), 1)
        self.assertEqual(self.client.calls[-1][0], 'getSongsByGenre')

    def test_artist_all_albums_and_progressive_tracks_and_album_drilldown(self):
        artist = self.library.browse({'category': 'artists'})['items'][0]
        result = self.library.artist(artist)
        self.assertEqual(len(result['albums']), 5)
        self.assertEqual(len(result['songs']), 2)
        self.assertTrue(result['songPaging']['hasMore'])
        page = self.library.artist_songs(result['songPaging'])
        self.assertEqual(page['offset'], 4)
        self.assertTrue(page['hasMore'])
        page = self.library.artist_songs(dict(artist=artist, offset=4))
        self.assertEqual(len(page['items']), 1)
        self.assertFalse(page['hasMore'])
        album = self.library.album(result['albums'][0])
        self.assertEqual(album['songs'][0]['title'], 'Song')

    def test_offline_cache_and_account_isolation(self):
        song = self.library.browse({})['items'][0]
        self.client.offline = True
        self.assertEqual(self.library.browse({'refresh': True})['items'][0], song)
        self.assertTrue(self.library.warning)
        with self.assertRaises(MusicError):
            self.library.album(dict(id='1', account='another'))


class StreamTests(unittest.TestCase):
    def test_revocation_while_upstream_opens_cannot_start_a_late_stream(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        entered = threading.Event()
        resume = threading.Event()
        response = io.BytesIO(b'audio')
        response.headers = {'Content-Type': 'audio/flac'}
        response.status = 200

        class SlowClient:
            account_id = 'fixture'

            def open(self, *args):
                entered.set()
                resume.wait(2)
                return response

        broker = StreamBroker(SlowClient)
        self.addCleanup(broker.close)
        url = broker.url(dict(id='one', account='fixture'))
        broker.bind('fixture', url)

        def read():
            try:
                with urlopen(url, timeout=2) as reply:
                    return reply.status
            except URLError as error:
                code = error.code
                error.close()
                return code

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(read)
            self.assertTrue(entered.wait(1))
            broker.release('fixture')
            resume.set()
            self.assertEqual(future.result(timeout=2), 404)
        self.assertTrue(response.closed)

    def test_gateway_forwards_range_and_auth_in_post_only_and_rejects_unknown_tickets(
        self,
    ):
        response = MagicMock()
        response.status = 206
        response.headers = {
            'Content-Type': 'audio/flac',
            'Content-Length': '5',
            'Content-Range': 'bytes 0-4/5',
        }
        response.read.side_effect = [b'audio', b'']
        opener = MagicMock()
        opener.open.return_value = response
        client = LibraryClient(
            dict(url='https://cloud.example/nc/', username='alice'),
            key='fixture-secret',
            opener=opener,
        )
        broker = StreamBroker(lambda: client)
        self.addCleanup(broker.close)
        url = broker.url(dict(id='s1', account=client.account_id))
        self.assertNotIn('fixture-secret', url)
        self.assertNotIn('cloud.example', url)
        from urllib.request import Request

        with urlopen(Request(url, headers={'Range': 'bytes=0-4'}), timeout=2) as reply:
            self.assertEqual(reply.status, 206)
            self.assertEqual(reply.read(), b'audio')
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, 'POST')
        self.assertNotIn('fixture-secret', request.full_url)
        self.assertEqual(parse_qs(request.data.decode())['p'], ['fixture-secret'])
        self.assertEqual(request.get_header('Range'), 'bytes=0-4')
        with self.assertRaises(URLError) as failure:
            urlopen(url.rsplit('/', 1)[0] + '/wrong', timeout=2)
        failure.exception.close()
        with self.assertRaises(MusicError):
            broker.url(dict(id='s1', account='another'))
        broker.bind('fixture-ipc', url)
        broker.release('fixture-ipc')
        with self.assertRaises(URLError) as failure:
            urlopen(url, timeout=1)
        failure.exception.close()
        broker.close()
        with self.assertRaises(URLError):
            urlopen(url, timeout=1)
