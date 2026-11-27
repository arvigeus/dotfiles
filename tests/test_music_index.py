"""Complete metadata snapshots keep all navigation local and preserve good data on failure."""

from contextlib import closing
from pathlib import Path
import tempfile
import threading
import time
import unittest
import sys
from unittest.mock import patch
from urllib.error import HTTPError
import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.music.cloud import CloudLibrary
from spaces.music.cloud_index import BATCH, PAGE
from spaces.music.remote_files import RemoteFiles
from integrations.nextcloud import NextcloudError
from integrations.subsonic import MusicError


class Catalogue:
    account_id = 'catalogue-fixture'

    def __init__(self, count=1203):
        self.count = count
        self.calls = []
        self.offline = False
        self.fail_offset = None
        self.block = None
        self.release = threading.Event()

    def request(self, method, **args):
        self.calls.append((method, args))
        if self.offline:
            raise MusicError('Offline')
        if self.block and method == 'search3':
            self.block.set()
            self.release.wait(5)
        if method == 'search3':
            if (
                self.fail_offset is not None
                and args.get('songOffset', 0) >= self.fail_offset
            ):
                raise MusicError('Page failed')
            groups = {}
            for kind, total in (
                ('song', self.count),
                ('album', (self.count + 9) // 10),
                ('artist', 20),
            ):
                offset = args.get(kind + 'Offset', 0)
                size = args.get(kind + 'Count', 0)
                groups[kind] = [
                    self.row(kind, i) for i in range(offset, min(total, offset + size))
                ]
            return dict(searchResult3=groups)
        if method == 'getSong':
            return dict(
                song=self.row('song', int(args['id'][1:])) | dict(title='Edited title')
            )
        raise AssertionError('Unexpected network request: ' + method)

    def row(self, kind, i):
        if kind == 'song':
            return dict(
                id='s' + str(i),
                title=('Café song ' if i == 1 else 'Song ') + f'{i:05}',
                artist='Artist ' + str((i // 10) % 20),
                artistId='a' + str((i // 10) % 20),
                album='Album ' + str(i // 10),
                albumId='b' + str(i // 10),
                genre='Rock' if i % 2 else 'Jazz',
                duration=100,
                path=f'/song-{i}.flac',
                track=i % 10 + 1,
                discNumber=1,
            )
        if kind == 'album':
            return dict(
                id='b' + str(i),
                name='Album ' + str(i),
                artist='Artist ' + str(i % 20),
                artistId='a' + str(i % 20),
                year=2020,
            )
        return dict(id='a' + str(i), name='Artist ' + str(i))


class CatalogueIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = Catalogue()
        self.library = CloudLibrary(self.client, Path(self.tmp.name) / 'cache')
        self.index = self.library.index
        self.addCleanup(self.index.stop)

    def build(self, force=True):
        self.index.next_refresh = 0
        self.index.start(force)
        self.index.thread.join(10)
        self.assertFalse(self.index.running)
        self.assertFalse(self.index.error, self.index.error)

    def test_missing_dav_subdirectory_is_empty_but_missing_music_root_is_an_error(self):
        with patch('spaces.music.remote_files.nextcloud.DAVClient'):
            remote = RemoteFiles(dict(url='https://example.test/', username='test'))
        remote.dav.home = 'https://example.test/'
        missing = NextcloudError('Not found')
        cause = HTTPError(remote.dav.home, 404, 'Not found', None, None)
        cause.close()
        missing.__cause__ = cause
        remote.dav.request.side_effect = missing
        self.assertEqual(remote.versions('removed'), {})
        with self.assertRaises(NextcloudError):
            remote.versions('')

    def test_full_catalogue_is_batched_and_search_filters_entities_are_offline(self):
        self.build()
        info = self.index.info()
        self.assertEqual(info['songs'], 1203)
        self.assertEqual(info['albums'], 121)
        self.assertEqual(
            [
                args['songOffset']
                for method, args in self.client.calls
                if method == 'search3'
            ],
            [0, 500, 1000, 1203],
        )
        self.client.offline = True
        self.client.calls.clear()
        page = self.library.browse({})
        self.assertEqual(page['total'], 1203)
        self.assertEqual(len(page['items']), PAGE)
        self.assertEqual(self.library.browse(dict(offset=1200))['total'], 1203)
        self.assertEqual(len(self.library.browse(dict(query='CAFE'))['items']), 1)
        self.assertEqual(self.library.browse(dict(genreName='Rock'))['total'], 601)
        self.assertEqual(len(self.library.genres()), 2)
        artist = self.index.lookup('artist', 'a0')
        detail = self.library.artist(artist)
        self.assertEqual(len(detail['albums']), 7)
        self.assertEqual(len(detail['songs']), 63)
        album = self.index.lookup('album', 'b0')
        tracks = self.library.album(album)['songs']
        self.assertEqual([item['trackNumber'] for item in tracks], list(range(1, 11)))
        scoped = self.library.entity_browse(
            dict(entity=artist, category='songs', query='01200')
        )
        self.assertEqual(scoped['items'][0]['id'], 's1200')
        self.assertEqual(self.client.calls, [])

    def test_lyrics_search_is_offline_and_refreshes_only_changed_files(self):
        songs = {i: self.client.row('song', i) for i in range(3)}
        self.client.count = len(songs)
        versions = {f'song-{i}.flac': f'audio-{i}' for i in songs}
        texts = {0: 'Coração\nunder the starlight', 1: 'Old chorus', 2: 'Removed verse'}
        requests = []
        roots = []
        root_version = 'initial-root'
        reading = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        class Files:
            def etag(self, rel):
                roots.append(rel)
                return root_version

            def versions(self, directory):
                requests.append(('dav', directory))
                return versions

        def request(method, **args):
            if method == 'getLyricsBySongId':
                identifier = int(args['id'][1:])
                requests.append(('lyrics', identifier))
                reading.set()
                release.wait(5)
                return dict(
                    lyricsList=dict(
                        structuredLyrics=[
                            dict(
                                synced=True,
                                line=[
                                    dict(value=line)
                                    for line in texts[identifier].splitlines()
                                ],
                            )
                        ]
                    )
                )
            result = original_request(method, **args)
            if method == 'search3':
                offset = args.get('songOffset', 0)
                count = args.get('songCount', 0)
                result['searchResult3']['song'] = list(songs.values())[
                    offset : offset + count
                ]
            return result

        original_request = self.client.request
        self.client.request = request
        self.client.lyrics_files = Files
        self.index.start(True)
        self.assertTrue(reading.wait(5))
        self.assertEqual(self.library.browse(dict(query='00000'))['total'], 1)
        release.set()
        self.index.thread.join(5)
        self.assertFalse(self.index.running)
        self.assertFalse(self.index.lyrics_error)
        self.assertEqual(
            set(requests), {('dav', ''), ('lyrics', 0), ('lyrics', 1), ('lyrics', 2)}
        )
        requests.clear()
        page = self.library.browse(dict(query='coracao starlight', genreName='Jazz'))
        self.assertEqual(
            self.library.browse(dict(query='coracao starlight', includeLyrics=False))[
                'total'
            ],
            0,
        )
        self.assertEqual([item['id'] for item in page['items']], ['s0'])
        self.assertNotIn('lyrics', page['items'][0])
        self.assertEqual(
            self.library.lyrics(page['items'][0])['lyrics'],
            'Coração\nunder the starlight',
        )
        self.assertEqual(
            self.library.queue(dict(query='old chorus'))['items'][0]['id'], 's1'
        )
        self.assertEqual(self.library.browse(dict(query='00000'))['total'], 1)
        self.assertEqual(requests, [])

        self.client.calls.clear()
        self.build(force=False)
        self.assertEqual(self.client.calls, [])
        self.assertEqual(requests, [])
        self.assertEqual(roots, ['', ''])

        with patch('spaces.music.cloud_index.CATALOGUE_RECHECK', 0):
            self.build(force=False)
        self.assertTrue(self.client.calls)
        self.assertEqual(requests, [])

        # The original cache only had folded text. Refresh keeps it valid.
        with closing(self.index.open_lyrics()) as database, database:
            database.execute("UPDATE lyrics SET display=NULL WHERE id='s0'")
        self.build()
        self.assertEqual(requests, [('dav', '')])
        self.assertEqual(self.library.browse(dict(query='coracao'))['total'], 1)
        requests.clear()
        self.assertEqual(
            self.library.lyrics(page['items'][0])['lyrics'],
            'Coração\nunder the starlight',
        )
        self.assertEqual(requests, [('lyrics', 0)])
        requests.clear()
        root_version = 'modified-root'
        versions['SONG-0.FLAC.LRC'] = 'new-sidecar'
        texts[0] = 'Changed sidecar'
        songs[1]['path'] = '/moved.flac'
        versions['moved.flac'] = versions.pop('song-1.flac')
        texts[1] = ''
        del songs[2], versions['song-2.flac']
        songs[3] = self.client.row('song', 3)
        versions['song-3.flac'] = 'audio-3'
        texts[3] = 'Fresh addition'
        self.build(force=False)
        self.assertEqual(
            set(requests), {('dav', ''), ('lyrics', 0), ('lyrics', 1), ('lyrics', 3)}
        )
        for query in ('coracao', 'old chorus', 'removed verse'):
            self.assertEqual(self.library.browse(dict(query=query))['total'], 0)
        for query in ('changed sidecar', 'fresh addition'):
            self.assertEqual(self.library.browse(dict(query=query))['total'], 1)
        requests.clear()
        self.build()
        self.assertEqual(requests, [('dav', '')])

        versions['song-0.flac'] = 'edited-audio'
        del versions['SONG-0.FLAC.LRC']
        texts[0] = 'Updated embedded lyrics'
        requests.clear()
        self.build()
        self.assertEqual(requests, [('dav', ''), ('lyrics', 0)])
        self.assertEqual(self.library.browse(dict(query='changed sidecar'))['total'], 0)
        self.assertEqual(
            self.library.browse(dict(query='updated embedded'))['total'], 1
        )

    def test_failed_partial_refresh_keeps_the_complete_previous_snapshot(self):
        self.build()
        before = self.index.path.read_bytes()
        self.client.count = 2000
        self.client.fail_offset = BATCH
        self.index.start(True)
        self.index.thread.join(10)
        self.assertTrue(self.index.error)
        self.assertEqual(self.index.path.read_bytes(), before)
        self.assertEqual(self.library.browse({})['total'], 1203)
        self.assertFalse(list(self.index.root.glob('.catalogue-*')))

    def test_navigation_never_waits_for_refresh_and_duplicate_refresh_is_coalesced(
        self,
    ):
        self.build()
        self.client.block = threading.Event()
        self.index.start(True)
        self.assertTrue(self.client.block.wait(2))
        thread = self.index.thread
        self.index.start(True)
        self.assertIs(self.index.thread, thread)
        start = time.monotonic()
        self.assertEqual(self.library.browse(dict(query='Song'))['total'], 1203)
        self.assertLess(time.monotonic() - start, 0.25)
        self.client.release.set()
        thread.join(10)

    def test_single_song_edits_update_cached_views_without_full_reload(self):
        self.build()
        song = self.index.lookup('song', 's0')
        self.library.refresh_item(song)
        self.assertEqual(self.index.lookup('song', 's0')['title'], 'Edited title')
        self.assertEqual(self.index.lookup('album', 'b0')['title'], 'Album 0')
        self.client.offline = True
        self.assertEqual(self.library.browse(dict(query='Edited title'))['total'], 1)

    def test_only_edits_during_a_refresh_override_its_server_snapshot(self):
        self.build()
        song = self.index.lookup('song', 's0')
        self.library.refresh_item(song)
        self.build()
        self.assertEqual(self.index.lookup('song', 's0')['title'], 'Song 00000')
        self.client.block = threading.Event()
        self.index.start(True)
        self.assertTrue(self.client.block.wait(2))
        self.library.refresh_item(song)
        self.client.release.set()
        self.index.thread.join(10)
        self.assertEqual(self.index.lookup('song', 's0')['title'], 'Edited title')
        self.assertEqual(self.index.lookup('album', 'b0')['releaseDate'], '2020')

    def test_account_scoping_and_private_cache_permissions(self):
        self.build()
        self.assertEqual(self.index.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.index.root.stat().st_mode & 0o777, 0o700)
        self.client.account_id = 'different-account'
        other = CloudLibrary(self.client, self.index.root)
        self.addCleanup(other.index.stop)
        self.assertFalse(other.index.info())

    def test_cancellation_never_publishes_an_incomplete_snapshot(self):
        self.build()
        before = self.index.path.read_bytes()
        self.client.block = threading.Event()
        self.index.start(True)
        self.assertTrue(self.client.block.wait(2))
        self.index.stop()
        self.client.release.set()
        self.index.thread.join(10)
        self.assertEqual(self.index.path.read_bytes(), before)
        self.assertFalse(list(self.index.root.glob('.catalogue-*')))
