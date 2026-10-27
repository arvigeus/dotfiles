"""The Series worker namespace covers metadata, torrents and subtitles together."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import support


class SeriesMediaTests(unittest.TestCase):
    def test_torrent_connection_is_shared_while_jobs_and_libraries_remain_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / 'config/quickshell/desktop/integrations/torrents.json'
            shared.parent.mkdir(parents=True)
            shared.write_text(
                '{"url":"https://example.invalid","password":"fixture-shared"}'
            )
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
from spaces.movies.paths import DATA, CONFIG_DIR, CACHE

media, torrents, subtitles = Backend(), TorrentBackend(), SubtitleBackend()
assert media.data == torrents.data == subtitles.data == DATA
assert DATA.name == CONFIG_DIR.name == CACHE.name == "series"
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
