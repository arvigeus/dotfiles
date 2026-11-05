"""The Series worker namespace covers metadata, torrents and subtitles together."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.movies.backend import Backend
from spaces.movies.local import LocalLibrary


class SeriesEpisodeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.backend = Backend(
            self.root / 'config/media.json', self.root / 'data', self.root / 'cache'
        )
        self.backend.config_path.write_text(json.dumps({'tmdb_key': 'fixture'}))
        self.backend.config_path.chmod(0o600)

    def test_refresh_bypasses_cached_seasons_and_episodes(self):
        show = dict(id='tt101', imdbId='tt101', kind='tv', title='Show', tmdbId=7)
        aired = []

        def api(path, **params):
            if path == 'tv/7':
                return {'seasons': [{'season_number': n} for n in range(len(aired))]}
            self.assertEqual(path, 'tv/7/season/1')
            return {
                'episodes': [
                    {'episode_number': n, 'name': f'E{n}', 'air_date': f'2026-11-0{n}'}
                    for n in range(1, len(aired) + 1)
                ]
            }

        with patch.object(self.backend, 'tmdb', side_effect=api):
            aired[:] = [0, 1]
            self.assertEqual(
                self.backend.episodes(dict(title=show))['seasons'], ['0', '1']
            )
            first = self.backend.episodes(dict(title=show, season='1'))
            aired.append(2)  # A new season and episode air within the cache hour.
            self.assertEqual(
                self.backend.episodes(dict(title=show))['seasons'], ['0', '1']
            )
            self.assertEqual(
                self.backend.episodes(dict(title=show, refresh=True))['seasons'],
                ['0', '1', '2'],
            )
            refreshed = self.backend.episodes(
                dict(title=show, season='1', refresh=True)
            )
            # The refreshed responses replace the cached ones for later reads.
            self.assertEqual(
                self.backend.episodes(dict(title=show))['seasons'], ['0', '1', '2']
            )
        self.assertEqual([row['number'] for row in first['items']], [1, 2])
        self.assertEqual([row['number'] for row in refreshed['items']], [1, 2, 3])
        # TMDB air dates appear like OMDb release dates and anime air dates.
        self.assertEqual(refreshed['items'][2]['date'], '2026-11-03')

    def test_local_episodes_follow_season_and_episode_order(self):
        library = LocalLibrary(self.root / 'data')
        show = dict(id='tt101', imdbId='tt101', kind='tv', title='Show', tmdbId=7)
        # Earlier imports may be stored under the TMDB alias of the same series.
        rows = [
            ('tmdb:tv:7', 2, 1),
            ('tt101', 1, 10),
            ('tmdb:tv:7', 1, 2),
            ('tt101', 0, 1),
            ('tt101', 1, 1),
        ]
        with library.db() as db:
            for identifier, season, episode in rows:
                path = self.root / f'Videos/S{season:02d}E{episode:02d}.mkv'
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b'fixture')
                db.execute(
                    'INSERT INTO local_files VALUES (?,?,?,?,?,?)',
                    ('tv', identifier, season, episode, str(path), json.dumps(show)),
                )
        self.assertEqual(
            [(row['season'], row['episode']) for row in library.files(show)],
            [(0, 1), (1, 1), (1, 2), (1, 10), (2, 1)],
        )


class SeriesMediaTests(unittest.TestCase):
    def test_torrent_connection_is_shared_while_jobs_and_libraries_remain_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / 'config/quickshell/desktop/integrations/torrents.json'
            shared.parent.mkdir(parents=True)
            shared.write_text(
                '{"url":"https://example.invalid","password":"fixture-shared"}'
            )
            shared.chmod(0o600)  # Credentials are accepted only from a private file.
            script = """
import os
from pathlib import Path
from spaces.movies.torrent_backend import TorrentBackend
backend = TorrentBackend()
space = os.environ["QUICKSHELL_MEDIA_SPACE"]
assert backend.config_path == Path(os.environ["XDG_CONFIG_HOME"]) / "quickshell/desktop/integrations/torrents.json"
assert backend.config()["password"] == "fixture-shared"
assert backend.data.name == space
assert backend.job_tag("fixture") == space + "-job-fixture"
"""
            for space in ('movies', 'series', 'games'):
                with self.subTest(space=space):
                    obsolete = (
                        root / f'config/quickshell/desktop/spaces/{space}/torrents.json'
                    )
                    obsolete.parent.mkdir(parents=True)
                    obsolete.write_text('{"password":"fixture-unused"}')
                    result = subprocess.run(
                        [sys.executable, '-c', script],
                        cwd=support.DESKTOP,
                        env={
                            **os.environ,
                            'QUICKSHELL_MEDIA_SPACE': space,
                            'XDG_CONFIG_HOME': str(root / 'config'),
                            'XDG_DATA_HOME': str(root / 'data'),
                        },
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )

    def test_owned_workers_share_series_records_without_touching_movies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = """
import json, os
from pathlib import Path
from spaces.movies.backend import Backend
from spaces.movies.torrent_backend import TorrentBackend
from spaces.movies.subtitle_backend import SubtitleBackend
from spaces.movies.local import media_sidecar_path
from spaces.movies.paths import DATA, CONFIG_DIR

media, torrents, subtitles = Backend(), TorrentBackend(), SubtitleBackend()
assert media.data == torrents.data == subtitles.data == DATA
assert DATA.name == CONFIG_DIR.name == "series"
assert media.config_path == subtitles.config_path == CONFIG_DIR / "media.json"
assert torrents.config_path == CONFIG_DIR.parents[1] / "integrations/torrents.json"
assert torrents.job_tag("fixture") == "series-job-fixture"
media.config_path.write_text(json.dumps({"providers":[{"name":"Fixture","series_url":"https://example.invalid/{imdbId}/{season}/{episode}"}]}))
show = dict(id="tt101",imdbId="tt101",kind="tv",title="Fixture series",season=2,episode=3)
source = Path(os.environ["XDG_VIDEOS_DIR"]) / "incoming.S02E03.mkv"
source.parent.mkdir(parents=True,exist_ok=True)
source.write_bytes(b"fixture")
path = Path(media.local.add(show,source,move=True))
assert path.is_file() and not source.exists()
assert "Series" in path.parts and "Season 02" in path.parts
assert media_sidecar_path(path).name.endswith(".series.json")
assert "seriesrelease" in path.with_suffix(".release.nfo").read_text()
assert torrents.library.files(show)[0]["path"] == str(path)
media.save(dict(title=show,values=dict(favorite=True)))
assert media.personal("tt101")["favorite"]
assert media.play(dict(title=show,season=2,episode=3))["command"][-1] == str(path)
assert media.play(dict(title=show,season=2,episode=3,online=True))["url"] == "https://example.invalid/tt101/2/3"
assert not (DATA.parent / "movies").exists()
"""
            result = subprocess.run(
                [sys.executable, '-c', script],
                cwd=support.DESKTOP,
                env={
                    **os.environ,
                    'QUICKSHELL_MEDIA_SPACE': 'series',
                    'XDG_CONFIG_HOME': str(root / 'config'),
                    'XDG_DATA_HOME': str(root / 'data'),
                    'XDG_CACHE_HOME': str(root / 'cache'),
                    'XDG_VIDEOS_DIR': str(root / 'Videos'),
                },
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
