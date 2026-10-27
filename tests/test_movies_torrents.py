import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
import sys
import support

sys.path.insert(0, str(support.DESKTOP))
from unittest.mock import patch

from spaces.movies.local import destination
from spaces.movies.torrent_backend import (
    QBitClient,
    QBitConnectionError,
    TorrentBackend,
    TorrentError,
    result_row,
    search_query,
)


class FakeQBit:
    def __init__(self):
        self.save_path = ''
        self.files = []
        self.calls = []
        self.tags = ''

    def call(self, path, values=None):
        self.calls.append((path, values))
        if path == 'search/plugins':
            return [{'name': 'public', 'enabled': True}]
        if path == 'search/start':
            return {'id': 42}
        if path.startswith('search/results'):
            return {
                'results': [
                    {
                        'fileName': 'The General (1998)',
                        'fileUrl': 'magnet:?xt=urn:btih:abc',
                        'nbSeeders': 8,
                    }
                ],
                'status': 'Stopped',
                'total': 1,
            }
        if path.startswith('search/status'):
            return [{'id': 1907502276, 'status': 'Running', 'total': 145}]
        if path == 'torrents/add':
            self.save_path = values['savepath']
            self.tags = values.get('tags', '')
            return 'Ok.'
        if path == 'torrents/fetchMetadata':
            return {
                'info': {
                    'files': [
                        {'path': file['name'], 'length': 100} for file in self.files
                    ]
                }
            }
        if path == 'torrents/delete':
            if values.get('deleteFiles') == 'true':
                for file in self.files:
                    (Path(self.save_path) / file['name']).unlink(missing_ok=True)
            self.save_path = ''
            return ''
        if path == 'torrents/renameFile':
            old = Path(self.save_path) / values['oldPath']
            new = Path(self.save_path) / values['newPath']
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
            for file in self.files:
                if file['name'] == values['oldPath']:
                    file['name'] = values['newPath']
            return ''
        if path == 'torrents/setLocation':
            new_root = Path(values['location'])
            for file in self.files:
                source = Path(self.save_path) / file['name']
                target = new_root / file['name']
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_file():
                    shutil.move(source, target)
            self.save_path = str(new_root)
            return ''
        if path == 'torrents/setAutoManagement':
            return ''
        if path == 'torrents/info':
            return (
                [
                    {
                        'save_path': self.save_path,
                        'tags': self.tags,
                        'progress': 1,
                        'hash': 'a' * 40,
                        'name': 'The General 1926 WEB-DL',
                    }
                ]
                if self.save_path
                else []
            )
        if path.startswith('torrents/files'):
            return self.files
        raise AssertionError(path)


class TorrentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(
            os.environ,
            {
                'XDG_VIDEOS_DIR': str(self.root / 'Videos'),
                'XDG_MUSIC_DIR': str(self.root / 'Music'),
                'XDG_DOCUMENTS_DIR': str(self.root / 'Documents'),
                'XDG_DATA_HOME': str(self.root / 'data'),
                'XDG_CONFIG_HOME': str(self.root / 'config'),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        # Import naming tests never depend on a user's configured catalogue providers.
        episodes = patch(
            'spaces.movies.backend.Backend.episodes',
            return_value={'items': [], 'next': ''},
        )
        episodes.start()
        self.addCleanup(episodes.stop)
        self.movie = {
            'id': 'tt0017925',
            'imdbId': 'tt0017925',
            'tmdbId': 961,
            'kind': 'movie',
            'title': 'The General',
            'year': 1926,
        }
        self.fake = FakeQBit()
        self.backend = TorrentBackend(
            self.root / 'config/torrents.json',
            self.root / 'data/quickshell/desktop/spaces/movies',
            self.fake,
        )

    def test_probe_only_offers_start_for_missing_local_process(self):
        with (
            patch.object(
                self.backend,
                'init',
                side_effect=QBitConnectionError('Web UI unreachable'),
            ),
            patch.object(self.backend, 'qbit_running', return_value=False),
            patch.object(
                self.backend, 'qbit_launcher', return_value=['/usr/bin/qbittorrent']
            ),
        ):
            self.assertTrue(self.backend.handle({'op': 'probe'})['canStart'])
            self.backend.config_path.parent.mkdir(parents=True)
            self.backend.config_path.write_text(
                json.dumps({'url': 'http://example.org:8080'})
            )
            self.assertFalse(self.backend.handle({'op': 'probe'})['canStart'])
            self.backend.config_path.write_text(
                json.dumps({'url': 'http://127.0.0.1:8080'})
            )
            with patch.object(self.backend, 'qbit_running', return_value=True):
                self.assertFalse(self.backend.handle({'op': 'probe'})['canStart'])
            with patch.object(self.backend, 'qbit_launcher', return_value=None):
                self.assertFalse(self.backend.handle({'op': 'probe'})['canStart'])
        with patch.object(
            self.backend, 'init', side_effect=TorrentError('Invalid credentials')
        ):
            with self.assertRaisesRegex(TorrentError, 'Invalid credentials'):
                self.backend.handle({'op': 'probe'})

    def test_start_qbittorrent_uses_installed_launcher_only_for_local_web_ui(self):
        with (
            patch.object(self.backend, 'qbit_running', return_value=False),
            patch.object(
                self.backend, 'qbit_launcher', return_value=['/usr/bin/qbittorrent']
            ),
            patch('spaces.movies.torrent_backend.subprocess.Popen') as launch,
        ):
            self.assertTrue(self.backend.handle({'op': 'start_qbittorrent'})['started'])
            launch.assert_called_once_with(
                ['uwsm', 'app', '-t', 'service', '--', '/usr/bin/qbittorrent'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.backend.config_path.parent.mkdir(parents=True)
            self.backend.config_path.write_text(
                json.dumps({'url': 'http://example.org:8080'})
            )
            with self.assertRaisesRegex(TorrentError, 'Only a local'):
                self.backend.handle({'op': 'start_qbittorrent'})
            launch.assert_called_once()
            self.backend.config_path.write_text(
                json.dumps({'url': 'http://127.0.0.1:8080'})
            )
            with patch.object(self.backend, 'qbit_running', return_value=True):
                self.assertFalse(
                    self.backend.handle({'op': 'start_qbittorrent'})['started']
                )
            launch.assert_called_once()

    def test_flatpak_launcher_is_supported(self):
        with (
            patch(
                'spaces.movies.torrent_backend.shutil.which',
                side_effect=lambda name: (
                    '/usr/bin/flatpak' if name == 'flatpak' else None
                ),
            ),
            patch('spaces.movies.torrent_backend.subprocess.run') as installed,
        ):
            installed.return_value.returncode = 0
            self.assertEqual(
                TorrentBackend.qbit_launcher(),
                ['/usr/bin/flatpak', 'run', 'org.qbittorrent.qBittorrent'],
            )

    def test_network_failure_is_distinct_from_web_ui_rejection(self):
        client = QBitClient({'url': 'http://127.0.0.1:8080'})
        with patch.object(
            client.opener, 'open', side_effect=urllib.error.URLError('offline')
        ):
            with self.assertRaises(QBitConnectionError):
                client.call('search/plugins')

    def test_context_search_and_wrong_year(self):
        self.assertEqual(search_query(self.movie), 'The General 1926')
        self.assertTrue(
            result_row({'fileName': 'The General (1998)'}, self.movie)['yearMismatch']
        )
        self.assertFalse(
            result_row({'fileName': 'The General 1926 1080p'}, self.movie)[
                'yearMismatch'
            ]
        )
        result = self.backend.handle({'op': 'search', 'title': self.movie})
        self.assertEqual(result['id'], 42)
        self.assertEqual(self.fake.calls[-1][1]['pattern'], 'The General 1926')
        episode = {
            'id': 'tt9',
            'kind': 'tv',
            'title': 'Example',
            'year': 2020,
            'season': 1,
            'episode': 2,
        }
        self.assertEqual(search_query(episode), 'Example S01E02')
        self.assertTrue(
            result_row({'fileName': 'Example 2020 S01E03'}, episode)['episodeMismatch']
        )
        self.assertEqual(
            search_query(
                {
                    'kind': 'music',
                    'scope': 'song',
                    'title': 'Prelude',
                    'artist': 'A Writer',
                    'releaseDate': '2020-07-03',
                }
            ),
            'A Writer Prelude 2020',
        )
        self.assertEqual(
            search_query(
                {
                    'kind': 'music',
                    'scope': 'album',
                    'title': 'First Album',
                    'artist': 'A Writer',
                    'releaseDate': '2020-07-03',
                }
            ),
            'A Writer First Album 2020',
        )
        self.assertEqual(
            search_query(
                {
                    'kind': 'music',
                    'scope': 'artist',
                    'title': 'A Writer',
                    'artist': 'A Writer',
                }
            ),
            'A Writer discography',
        )
        self.assertEqual(
            search_query({'kind': 'tv', 'id': 'tt9', 'title': 'Example', 'year': 2020}),
            'Example complete',
        )
        self.assertEqual(
            search_query(
                {
                    'kind': 'tv',
                    'id': 'tt9',
                    'title': 'Example',
                    'year': 2020,
                    'season': 2,
                }
            ),
            'Example S02',
        )
        self.assertTrue(
            result_row({'fileName': 'Example S01E01'}, {'kind': 'tv', 'season': 2})[
                'seasonMismatch'
            ]
        )

    def test_results_uses_qbittorrent_job_id_not_worker_request_id(self):
        self.backend.handle(
            {
                'op': 'results',
                'id': 7,
                'job_id': 1907502276,
                'title': self.movie,
                'offset': 0,
            }
        )
        self.assertEqual(
            self.fake.calls[-1][0], 'search/results?id=1907502276&limit=100&offset=0'
        )
        self.assertEqual(
            self.backend.handle({'op': 'status', 'id': 8, 'job_id': 1907502276}),
            {'running': True, 'total': 145},
        )
        self.assertEqual(self.fake.calls[-1][0], 'search/status?id=1907502276')

    def test_completed_movie_import_moves_seeding_source_and_ids(self):
        queued = self.backend.handle(
            {'op': 'queue', 'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'}
        )
        source = Path(self.fake.save_path) / 'The.General.1926.mkv'
        source.write_bytes(b'video' * 250000)
        subtitle = source.with_suffix('.srt')
        language_subtitle = source.with_name(source.stem + '-bg.srt')
        added_later = source.with_name(source.stem + '.en.srt')
        for path in (subtitle, language_subtitle):
            path.write_text('subtitle')
        added_later.write_text('later subtitle')
        self.fake.files = [
            {'name': path.name, 'priority': 1}
            for path in (source, subtitle, language_subtitle)
        ]
        jobs = self.backend.handle({'op': 'jobs'})
        self.assertEqual(jobs[0]['status'], 'imported')
        target = destination(self.movie, source)
        self.assertFalse(source.exists())
        self.assertTrue(target.is_file())
        self.assertTrue(target.with_suffix('.srt').is_file())
        self.assertTrue(target.with_name(target.stem + '-bg.srt').is_file())
        self.assertEqual(
            target.with_name(target.stem + '.en.srt').read_text(), 'later subtitle'
        )
        self.assertFalse(subtitle.exists())
        self.assertFalse(added_later.exists())
        self.assertIn(
            (
                'torrents/renameFile',
                {
                    'hash': 'a' * 40,
                    'oldPath': language_subtitle.name,
                    'newPath': target.stem + '-bg.srt',
                },
            ),
            self.fake.calls,
        )
        self.assertFalse(
            any(
                path == 'torrents/renameFile' and values['oldPath'] == added_later.name
                for path, values in self.fake.calls
            )
        )
        self.assertFalse(
            any(path == 'torrents/setLocation' for path, _ in self.fake.calls)
        )
        self.assertEqual(self.backend.library.files(self.movie)[0]['path'], str(target))
        nfo = (target.parent / 'movie.nfo').read_text()
        self.assertIn('tt0017925', nfo)
        self.assertIn('961', nfo)
        self.assertIn('The General 1926 WEB-DL', nfo)
        self.assertIn('The.General.1926.mkv', nfo)
        self.assertIn('qBittorrent', nfo)
        self.assertEqual(
            self.backend.handle({'op': 'local_list', 'kind': 'movie'})[0]['id'],
            self.movie['id'],
        )
        self.assertEqual(jobs[0]['id'], queued['id'])
        self.assertEqual(self.backend.jobs({})[0]['progress'], 1)

    def test_video_queue_downloads_directly_into_title_folder(self):
        queued = self.backend.queue(
            {'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'}
        )
        folder = self.root / 'Videos/Movies/The General (1926)'
        self.assertEqual(Path(queued['savePath']), folder)
        self.assertEqual(Path(self.fake.save_path), folder)
        self.assertIn(self.backend.job_tag(queued['id']), self.fake.tags)
        with self.backend.db() as db:
            saved = Path(
                db.execute('SELECT save_path FROM torrent_downloads').fetchone()[0]
            )
        self.assertEqual(saved, folder)
        self.assertFalse((self.backend.data / 'torrents').exists())

    def test_duplicate_queue_is_rejected_without_a_second_add(self):
        request = {'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'}
        self.backend.queue(request)
        with self.assertRaisesRegex(TorrentError, 'already tracked'):
            self.backend.queue(request)
        self.assertEqual(sum(path == 'torrents/add' for path, _ in self.fake.calls), 1)

    def test_untagged_torrent_in_title_folder_does_not_claim_job(self):
        queued = self.backend.queue(
            {'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'}
        )
        torrents = [
            {
                'hash': 'b' * 40,
                'save_path': queued['savePath'],
                'progress': 1,
                'tags': '',
            }
        ]
        with patch.object(self.fake, 'call', return_value=torrents):
            job = self.backend.jobs({})[0]
        self.assertEqual(job['status'], 'queued')
        self.assertEqual(job['progress'], 0)
        with self.backend.db() as db:
            self.assertEqual(
                db.execute('SELECT torrent_hash FROM torrent_downloads').fetchone()[0],
                '',
            )

    def test_unaccepted_download_uses_persisted_queue_time(self):
        with patch('spaces.movies.torrent_backend.time.time', return_value=1000):
            self.backend.queue({'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'})
        with (
            patch.object(self.fake, 'call', return_value=[]),
            patch('spaces.movies.torrent_backend.time.time', return_value=1121),
        ):
            job = self.backend.jobs({})[0]
        self.assertFalse(job['active'])
        self.assertIn('did not add', job['message'])

    def test_download_resumes_by_tag_after_worker_reopens(self):
        self.backend.queue({'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'})
        source = Path(self.fake.save_path) / 'The.General.1926.mkv'
        source.write_bytes(b'video' * 250000)
        self.fake.files = [{'name': source.name, 'priority': 1}]
        reopened = TorrentBackend(
            self.backend.config_path, self.backend.data, self.fake
        )
        self.assertEqual(reopened.jobs({})[0]['status'], 'imported')
        self.assertTrue(destination(self.movie, source).is_file())
        self.assertFalse(source.exists())

    def test_scan_never_imports_incomplete_torrent_as_ordinary_video(self):
        folder = self.root / 'Videos/Movies/Incomplete'
        folder.mkdir(parents=True)
        source = folder / 'The.General.1926.mkv'
        source.write_bytes(b'partial video')
        self.fake.save_path = str(folder)
        self.fake.files = [{'name': source.name, 'priority': 1}]
        torrents = [{'save_path': str(folder), 'hash': 'a' * 40, 'progress': 0.2}]
        from spaces.movies.scanner import candidates

        self.assertEqual(
            list(
                candidates(
                    'movie', self.root / 'Videos/Movies', self.fake, torrents=torrents
                )
            ),
            [],
        )
        self.assertTrue(source.exists())

    def test_scan_with_unavailable_qbittorrent_excludes_tracked_title_folder(self):
        self.backend.queue({'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'})
        source = Path(self.fake.save_path) / 'The.General.1926.mkv'
        source.write_bytes(b'partial video' * 250000)
        with patch.object(
            self.fake, 'call', side_effect=QBitConnectionError('Offline')
        ):
            result = self.backend.scan({'kind': 'movie'})
        self.assertEqual(result['imported'], [])
        self.assertEqual(result['review'], [])
        self.assertTrue(source.exists())

    def test_jobs_waits_while_qbittorrent_is_moving_completed_files(self):
        self.backend.queue({'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'})
        torrents = [
            {
                'save_path': self.fake.save_path,
                'hash': 'a' * 40,
                'tags': self.fake.tags,
                'progress': 1,
                'state': 'moving',
            }
        ]
        with patch.object(self.fake, 'call', return_value=torrents):
            jobs = self.backend.jobs({})
        self.assertEqual(jobs[0]['status'], 'moving')
        self.assertTrue(jobs[0]['active'])

    def test_delete_unlinked_job_uses_tag_and_preserves_shared_folder(self):
        show = {'kind': 'tv', 'id': 'tt9', 'title': 'Example', 'year': 2020}
        queued = self.backend.queue({'title': show, 'url': 'magnet:?xt=urn:btih:abc'})
        unrelated = Path(self.fake.save_path) / 'other-episode.mkv'
        unrelated.write_bytes(b'another download')
        self.backend.delete_job({'job_id': queued['id']})
        self.assertTrue(unrelated.exists())
        self.assertIn(
            ('torrents/delete', {'hashes': 'a' * 40, 'deleteFiles': 'true'}),
            self.fake.calls,
        )

    def test_ambiguous_movie_requires_explicit_file(self):
        queued = self.backend.handle(
            {'op': 'queue', 'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'}
        )
        staging = Path(self.fake.save_path)
        for name in ('The.General.1926.mkv', 'The.General.1998.mkv'):
            (staging / name).write_bytes(b'video' * 250000)
        self.fake.files = [
            {'name': name, 'priority': 1}
            for name in ('The.General.1926.mkv', 'The.General.1998.mkv')
        ]
        self.assertEqual(self.backend.handle({'op': 'jobs'})[0]['status'], 'review')
        files = self.backend.handle({'op': 'review', 'job_id': queued['id']})
        self.assertEqual(len(files), 2)
        self.backend.handle(
            {
                'op': 'import_selected',
                'job_id': queued['id'],
                'path': 'The.General.1926.mkv',
            }
        )
        self.assertEqual(self.backend.handle({'op': 'jobs'})[0]['status'], 'imported')

    def test_movie_content_year_mismatch_requires_review(self):
        self.backend.handle(
            {'op': 'queue', 'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'}
        )
        source = Path(self.fake.save_path) / 'The.General.1998.mkv'
        source.write_bytes(b'video' * 250000)
        self.fake.files = [{'name': source.name, 'priority': 1}]
        jobs = self.backend.handle({'op': 'jobs'})
        self.assertEqual(jobs[0]['status'], 'review')
        self.assertIn('different year', jobs[0]['message'])
        self.assertFalse(destination(self.movie, source).exists())

    def test_scan_moves_unmanaged_movie_with_nfo_and_deletes_related_files(self):
        incoming = self.root / 'Incoming'
        incoming.mkdir()
        source = incoming / 'The.General.1926.mkv'
        source.write_bytes(b'video')
        subtitle = incoming / 'English.srt'
        subtitle.write_text('subtitle')
        (incoming / 'movie.nfo').write_text(
            '<movie><title>The General</title><year>1926</year>'
            '<uniqueid type="imdb">tt0017925</uniqueid></movie>'
        )
        (incoming / 'unrelated.txt').write_text('extra')
        result = self.backend.handle(
            {'op': 'scan', 'kind': 'movie', 'path': str(incoming)}
        )
        self.assertEqual(len(result['imported']), 1)
        self.assertFalse(source.exists())
        target = Path(result['imported'][0]['path'])
        self.assertTrue(target.is_file())
        self.assertFalse(subtitle.exists())
        self.assertEqual(target.with_suffix('.srt').read_text(), 'subtitle')
        self.assertTrue((target.parent / 'movie.nfo').exists())
        self.backend.handle({'op': 'delete_local', 'path': str(target)})
        self.assertFalse(target.exists())
        self.assertFalse((target.parent / 'movie.nfo').exists())
        self.assertFalse(target.parent.exists())

    @unittest.skipUnless(
        __import__('importlib').util.find_spec('guessit'), 'python-guessit is required'
    )
    def test_scan_does_not_guess_unmatched_subtitle_in_multi_video_folder(self):
        incoming = self.root / 'Incoming'
        incoming.mkdir()
        for name in ('First.2024.mkv', 'Second.2025.mkv'):
            (incoming / name).write_bytes(b'video')
        subtitle = incoming / 'English.srt'
        subtitle.write_text('subtitle')
        titles = {
            '2024': self.movie
            | {'id': 'tt-first', 'imdbId': 'tt-first', 'title': 'First', 'year': 2024},
            '2025': self.movie
            | {
                'id': 'tt-second',
                'imdbId': 'tt-second',
                'title': 'Second',
                'year': 2025,
            },
        }
        with patch(
            'spaces.movies.torrent_backend.catalogue_match',
            side_effect=lambda _catalogue, _kind, parsed: titles[str(parsed['year'])],
        ):
            result = self.backend.handle(
                {'op': 'scan', 'kind': 'movie', 'path': str(incoming)}
            )
        self.assertEqual(len(result['imported']), 2)
        self.assertTrue(subtitle.exists())
        self.assertFalse(
            any(
                Path(row['path']).with_suffix('.srt').exists()
                for row in result['imported']
            )
        )

    def test_movie_scan_ignores_completed_tv_torrent(self):
        incoming = self.root / 'Incoming'
        incoming.mkdir()
        self.fake.save_path = str(incoming)
        name = '01E01.The.Crocodiles.Dilemma.mkv'
        (incoming / name).write_bytes(b'video')
        self.fake.files = [{'name': name, 'priority': 1}]
        result = self.backend.handle({'op': 'scan', 'kind': 'movie'})
        self.assertEqual(result['review'], [])

    def test_scan_keeps_uncertain_movie_for_explicit_catalogue_match(self):
        incoming = self.root / 'Incoming'
        incoming.mkdir()
        source = incoming / 'The.General.1926.mkv'
        source.write_bytes(b'video')
        with patch('spaces.movies.torrent_backend.catalogue_match', return_value=None):
            result = self.backend.handle(
                {'op': 'scan', 'kind': 'movie', 'path': str(incoming)}
            )
        self.assertEqual(len(result['review']), 1)
        self.assertTrue(source.exists())
        token = result['review'][0]['token']
        imported = self.backend.handle(
            {'op': 'scan_import', 'token': token, 'title': self.movie}
        )
        self.assertTrue(Path(imported['path']).exists())
        self.assertFalse(source.exists())

    def test_scan_existing_qbit_file_moves_seeding_source(self):
        incoming = self.root / 'Incoming'
        incoming.mkdir()
        self.fake.save_path = str(incoming)
        source = incoming / 'The.General.1926.mkv'
        source.write_bytes(b'video')
        subtitle = incoming / 'English.srt'
        subtitle.write_text('subtitle')
        self.fake.files = [
            {'name': source.name, 'priority': 1},
            {'name': subtitle.name, 'priority': 1},
        ]
        (incoming / 'movie.nfo').write_text(
            '<movie><title>The General</title><year>1926</year>'
            '<uniqueid type="imdb">tt0017925</uniqueid></movie>'
        )
        result = self.backend.handle(
            {'op': 'scan', 'kind': 'movie', 'path': str(incoming)}
        )
        self.assertEqual(len(result['imported']), 1)
        self.assertFalse(source.exists())
        self.assertFalse(subtitle.exists())
        self.assertTrue(
            Path(result['imported'][0]['path']).with_suffix('.srt').exists()
        )
        self.assertTrue(self.backend.library.files(self.movie)[0]['torrent'])

    def test_scan_does_not_overwrite_existing_library_file(self):
        incoming = self.root / 'Incoming'
        incoming.mkdir()
        self.fake.save_path = str(incoming)
        source = incoming / 'The.General.1926.mkv'
        source.write_bytes(b'video')
        self.fake.files = [{'name': source.name, 'priority': 1}]
        target = Path(self.backend.library.add(self.movie, source))
        with patch(
            'spaces.movies.torrent_backend.catalogue_match', return_value=self.movie
        ):
            result = self.backend.handle({'op': 'scan', 'kind': 'movie'})
        self.assertEqual(len(result['imported']), 0)
        self.assertEqual(len(result['review']), 1)
        self.assertIn('already exists', result['review'][0]['reason'])
        self.assertTrue(source.exists())
        self.assertTrue(target.is_file())

    def test_torrent_import_does_not_overwrite_library_subtitle(self):
        incoming = self.root / 'Incoming'
        incoming.mkdir()
        self.fake.save_path = str(incoming)
        source = incoming / 'The.General.1926.mkv'
        subtitle = source.with_suffix('.srt')
        source.write_bytes(b'video')
        subtitle.write_bytes(b'incoming subtitle')
        self.fake.files = [
            {'name': path.name, 'priority': 1} for path in (source, subtitle)
        ]
        target = destination(self.movie, source)
        target.parent.mkdir(parents=True)
        target.with_suffix('.srt').write_bytes(b'existing subtitle')
        with patch(
            'spaces.movies.torrent_backend.catalogue_match', return_value=self.movie
        ):
            result = self.backend.handle(
                {'op': 'scan', 'kind': 'movie', 'path': str(incoming)}
            )
        self.assertEqual(result['imported'], [])
        self.assertIn('subtitle already exists', result['review'][0]['reason'])
        self.assertTrue(source.exists())
        self.assertTrue(subtitle.exists())
        self.assertEqual(target.with_suffix('.srt').read_bytes(), b'existing subtitle')

    def test_deleting_torrent_import_removes_torrent_and_library_link(self):
        self.backend.handle(
            {'op': 'queue', 'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'}
        )
        source = Path(self.fake.save_path) / 'The.General.1926.mkv'
        source.write_bytes(b'video' * 250000)
        self.fake.files = [{'name': source.name, 'priority': 1}]
        self.backend.handle({'op': 'jobs'})
        target = destination(self.movie, source)
        self.assertTrue(self.backend.library.files(self.movie)[0]['torrent'])
        result = self.backend.handle({'op': 'delete_local', 'path': str(target)})
        self.assertTrue(result['torrent'])
        self.assertFalse(target.exists())
        self.assertEqual(self.backend.library.files(self.movie), [])
        self.assertIn(
            ('torrents/delete', {'hashes': 'a' * 40, 'deleteFiles': 'true'}),
            self.fake.calls,
        )

    def test_delete_job_removes_tracked_download_without_local_file(self):
        queued = self.backend.handle(
            {'op': 'queue', 'title': self.movie, 'url': 'magnet:?xt=urn:btih:abc'}
        )
        staging = Path(self.fake.save_path)
        download = staging / 'The.General.1926.mkv'
        download.write_bytes(b'video')
        self.fake.files = [{'name': download.name, 'priority': 1}]
        with self.backend.db() as db:
            db.execute(
                "UPDATE torrent_downloads SET status='imported' WHERE id=?",
                (queued['id'],),
            )
        result = self.backend.handle({'op': 'delete_job', 'job_id': queued['id']})
        self.assertTrue(result['torrent'])
        self.assertFalse(staging.exists())
        with self.backend.db() as db:
            self.assertIsNone(
                db.execute(
                    'SELECT id FROM torrent_downloads WHERE id=?', (queued['id'],)
                ).fetchone()
            )

    def test_local_default_needs_no_config_file(self):
        self.assertEqual(self.backend.config(), {'url': 'http://127.0.0.1:8080'})


if __name__ == '__main__':
    unittest.main()
