"""The merged library observes local music without mutating media or the server."""

from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import support
from test_music_index import Catalogue

sys.path.insert(0, str(support.DESKTOP))
from spaces.music import local_files as files, tags
from spaces.music.cloud import CloudLibrary
from spaces.music.inventory import Inventory


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.music = self.root / 'Music'
        self.music.mkdir()
        self.client = Catalogue(230)
        self.library = CloudLibrary(self.client, self.root / 'cache')
        self.index = self.library.index
        self.index.start(True)
        self.index.thread.join(5)
        self.addCleanup(self.index.stop)
        self.inventory = Inventory(self.index)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(files, 'ROOT', self.music))
        self.stack.enter_context(patch.object(files, 'DATA', self.root / 'data'))
        self.stack.enter_context(
            patch.object(files, 'account_id', return_value=self.client.account_id)
        )
        self.stack.enter_context(
            patch.object(
                files,
                'metadata',
                side_effect=AssertionError('Observation must not contact DAV'),
            )
        )
        self.client.offline = True
        self.client.calls.clear()

    def song(self, name, title='New song', artist='Artist 0', album='Album 0'):
        path = self.music / name
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                'ffmpeg',
                '-v',
                'error',
                '-f',
                'lavfi',
                '-i',
                'anullsrc',
                '-t',
                '0.05',
                '-metadata',
                'title=' + title,
                '-metadata',
                'artist=' + artist,
                '-metadata',
                'album=' + album,
                str(path),
            ],
            check=True,
        )
        return path

    def test_new_songs_tags_entities_queue_and_search_are_available_offline(self):
        self.song('new.flac')
        self.assertTrue(self.inventory.refresh()['changed'])
        songs = self.library.browse({'query': 'New song'})
        self.assertEqual(songs['total'], 1)
        self.assertTrue(songs['items'][0]['notUploaded'])
        self.assertEqual(self.library.browse({'pending': True})['total'], 1)
        self.assertEqual(self.library.browse({'category': 'artists'})['total'], 20)
        artist = self.index.lookup('artist', 'a0')
        self.assertIn(
            'New song',
            [
                s['title']
                for s in self.library.entity_browse(
                    dict(entity=artist, category='songs')
                )['items']
            ],
        )
        self.assertEqual(len(self.library.queue({})['items']), 231)
        self.assertEqual(self.client.calls, [])
        with patch.object(
            tags,
            'read',
            side_effect=AssertionError('Unchanged files should not be reprobed'),
        ):
            self.assertFalse(self.inventory.refresh()['changed'])

    def test_cache_is_deduplicated_and_removing_bytes_keeps_remote_song(self):
        path = self.song('song-0.flac', title='Song 00000')
        files.remember(
            self.client.account_id, 'song-0.flac', path, {'Size': path.stat().st_size}
        )
        self.inventory.refresh()
        self.assertEqual(self.library.browse({})['total'], 230)
        song = self.index.lookup('song', 's0')
        self.assertTrue(song['local'])
        self.assertFalse(song['notUploaded'])
        path.unlink()
        self.inventory.refresh()
        self.assertEqual(self.library.browse({})['total'], 230)
        self.assertNotIn('local', self.index.lookup('song', 's0'))
        self.assertEqual(self.client.calls, [])

    def test_local_edits_update_search_and_failed_refresh_keeps_readable_snapshot(self):
        path = self.song('draft.flac')
        self.inventory.refresh()
        tags.write(
            path,
            {'title': 'Edited café'},
            files.run,
            files.signature,
            files.register,
            files.unregister,
        )
        self.inventory.refresh()
        self.assertEqual(self.library.browse({'query': 'edited cafe'})['total'], 1)
        self.assertEqual(self.library.browse({'query': 'New song'})['total'], 0)
        before = self.inventory.view.read_bytes()
        with patch.object(self.inventory, '_publish', side_effect=OSError('Disk full')):
            self.song('another.flac')
            with self.assertRaises(OSError):
                self.inventory.refresh()
        self.assertEqual(self.inventory.view.read_bytes(), before)
        self.assertEqual(self.library.browse({'query': 'edited'})['total'], 1)
        self.assertTrue(self.inventory.refresh()['changed'])
        self.assertEqual(self.library.browse({'query': 'New song'})['total'], 1)

    def test_local_information_is_passive_and_save_explicitly_uploads(self):
        path = self.song('new.flac')
        song = dict(
            id='local:new.flac',
            kind='song',
            source='music-local',
            account=self.client.account_id,
            serverPath='/new.flac',
            notUploaded=True,
        )
        opened = files.file_job(dict(action='info', song=song))
        with patch.object(
            files, 'publish', return_value=dict(path=str(path), synced=True)
        ) as publish:
            result = files.file_job(
                dict(
                    action='save',
                    song=song,
                    tags={'title': 'Changed'},
                    signature=opened['signature'],
                )
            )
        publish.assert_called_once_with(path, create=True)
        self.assertTrue(result['synced'])
        self.assertEqual(tags.read(path, files.run)['tags']['title'], 'Changed')
        path.write_bytes(path.read_bytes() + b'changed outside editor')
        with self.assertRaises(files.MusicError):
            files.file_job(
                dict(
                    action='save',
                    song=song,
                    tags={'title': 'Stale'},
                    signature=opened['signature'],
                )
            )

    def test_missing_remote_index_does_not_prevent_local_browsing_or_later_index_build(
        self,
    ):
        self.index.path.unlink()
        self.song('new.flac')
        self.inventory.refresh()
        self.assertEqual(self.library.browse({})['total'], 1)
        self.index.attempted = False
        self.client.offline = False
        self.index.start()
        self.index.thread.join(5)
        self.assertFalse(self.index.error)
        self.inventory.refresh()
        self.assertEqual(self.library.browse({})['total'], 231)

    def test_local_move_stays_offline_and_rejects_traversal_and_collisions(self):
        path = self.song('old.flac')
        result = files.move(path, 'Artist/Album/new.flac', remote_allowed=False)
        self.assertFalse(path.exists())
        self.assertTrue(Path(result['path']).is_file())
        for target in (
            '../escape.flac',
            '/absolute.flac',
            'Artist/Album/new.flac/../wrong.flac',
        ):
            with self.assertRaises(files.MusicError):
                files.move(result['path'], target, remote_allowed=False)
        taken = self.song('taken.flac')
        with self.assertRaises(files.MusicError):
            files.move(result['path'], 'taken.flac', remote_allowed=False)
        self.assertTrue(taken.exists())

    def test_mp3_flac_and_m4a_tag_edits_keep_audio_and_lyrics(self):
        for extension in ('mp3', 'flac', 'm4a'):
            with self.subTest(extension=extension):
                path = self.song('song.' + extension)
                tags.write(
                    path,
                    {'title': 'New title', 'lyrics': 'First line\nSecond line'},
                    files.run,
                    files.signature,
                    files.register,
                    files.unregister,
                )
                details = tags.read(path, files.run)
                self.assertEqual(details['tags']['title'], 'New title')
                self.assertEqual(details['tags']['lyrics'], 'First line\nSecond line')
                self.assertGreater(details['duration'], 0)

    def test_explicit_upload_is_visible_before_server_catalogue_indexes_it(self):
        path = self.song('new.flac')
        song = dict(
            id='local:new.flac',
            source='music-local',
            account=self.client.account_id,
            serverPath='/new.flac',
            notUploaded=True,
        )
        files.remember(
            self.client.account_id, 'new.flac', path, {'Size': path.stat().st_size}
        )
        with patch.object(
            files, 'publish', return_value=dict(synced=True, path=str(path))
        ):
            files.file_job(dict(action='upload', song=song))
        self.inventory.refresh()
        item = self.library.browse({'query': 'New song'})['items'][0]
        self.assertFalse(item['notUploaded'])
        self.assertFalse(item['pendingUpload'])
        self.assertTrue(item['awaitingIndex'])
        self.assertEqual(self.library.browse({'pending': True})['total'], 0)

    def test_synchronized_local_tags_override_lagging_server_metadata(self):
        path = self.song('song-0.flac', title='Already saved title')
        files.remember(
            self.client.account_id, 'song-0.flac', path, {'Size': path.stat().st_size}
        )
        self.inventory.refresh()
        result = self.library.browse({'query': 'Already saved title'})
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['id'], 's0')
        self.assertFalse(result['items'][0]['pendingUpload'])

    def test_pending_remote_move_stays_one_uploaded_song_until_catalogue_acknowledges(
        self,
    ):
        path = self.song('song-0.flac', title='Song 00000')
        files.remember(
            self.client.account_id, 'song-0.flac', path, {'Size': path.stat().st_size}
        )
        self.inventory.refresh()
        song = self.index.lookup('song', 's0')
        new = self.music / 'renamed.flac'
        path.rename(new)
        with files.db() as db:
            db.execute(
                'UPDATE music_cache SET path=? WHERE account=? AND path=?',
                ('renamed.flac', self.client.account_id, 'song-0.flac'),
            )
            db.execute(
                'INSERT INTO music_pending_moves VALUES(?,?,?,?)',
                (
                    self.client.account_id,
                    'song-0.flac',
                    'renamed.flac',
                    json.dumps(song | dict(serverPath='/renamed.flac')),
                ),
            )
        self.inventory.refresh()
        items = self.library.browse({'query': 'Song 00000'})['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['id'], 's0')
        self.assertFalse(items[0]['notUploaded'])
        self.assertEqual(items[0]['serverPath'], '/renamed.flac')
        # Local removal still leaves one server record with the moved path.
        new.unlink()
        self.inventory.refresh()
        self.assertEqual(self.index.lookup('song', 's0')['serverPath'], '/renamed.flac')
        self.index.update_song(song | dict(serverPath='/renamed.flac'))
        self.inventory.refresh(True)
        with files.db() as db:
            self.assertEqual(
                db.execute('SELECT count(*) FROM music_pending_moves').fetchone()[0], 0
            )
