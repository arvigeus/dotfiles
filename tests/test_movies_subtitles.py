import io
import json
import os
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing
from pathlib import Path
import sys
import support
sys.path.insert(0, str(support.DESKTOP))
from types import SimpleNamespace
from unittest.mock import patch

from spaces.movies.local import LocalLibrary, subtitle_associations
from spaces.movies.subtitle_backend import OpenSubtitles, SubtitleBackend, SubtitleError, moviehash

SRT = b"1\n00:00:25,000 --> 00:00:27,000\nHello\n"


class FakeOpenSubtitles:
    def __init__(self):
        self.calls = []

    def request(self, path, params=None, **kwargs):
        self.calls.append((path, params))
        if path != "/subtitles":
            raise AssertionError(path)
        rows = []
        for code in params["languages"].split(","):
            file_id = {"bg": 10, "vi": 20, "en": 30}[code]
            rows.append(
                {
                    "attributes": {
                        "language": code,
                        "fps": 25,
                        "release": "Example 1080p WEB-DL",
                        "from_trusted": True,
                        "download_count": 8,
                        "feature_details": {"season_number": 1, "episode_number": 2},
                        "files": [{"file_id": file_id, "file_name": code + ".srt"}],
                    }
                }
            )
        return {"data": rows}

    def download(self, file_id):
        self.calls.append(("download", file_id))
        return SRT, 18


class SubtitleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"XDG_VIDEOS_DIR": str(self.root / "Videos")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.data = self.root / "data"
        self.library = LocalLibrary(self.data)
        self.client = FakeOpenSubtitles()
        self.backend = SubtitleBackend(self.root / "config/media.json", self.data, self.client)
        self.title = {
            "kind": "movie",
            "id": "tt123",
            "imdbId": "tt123",
            "title": "Example",
            "year": 2025,
        }
        source = self.root / "Example.2025.WEB-DL.mkv"
        source.write_bytes(b"12345678" * 17000)
        self.video = Path(
            self.library.add(self.title, source, move=True, release_name="Example 1080p WEB-DL")
        )

    def test_import_moves_matching_subtitles_and_preserves_language_suffix(self):
        incoming = self.root / "Incoming"
        incoming.mkdir()
        source = incoming / "Another.Movie.2024.mp4"
        source.write_bytes(b"video")
        plain = incoming / "Another.Movie.2024.srt"
        bulgarian = incoming / "Another.Movie.2024-bg.srt"
        plain.write_bytes(SRT)
        bulgarian.write_bytes(SRT)
        title = self.title | {
            "id": "tt456",
            "imdbId": "tt456",
            "title": "Another Movie",
            "year": 2024,
        }
        target = Path(self.library.add(title, source, move=True))
        self.assertEqual(target.name, "Another Movie (2024).mp4")
        self.assertFalse(plain.exists())
        self.assertFalse(bulgarian.exists())
        self.assertEqual(target.with_suffix(".srt").read_bytes(), SRT)
        self.assertEqual(target.with_name(target.stem + "-bg.srt").read_bytes(), SRT)

    def test_import_moves_lone_unmatched_subtitle_but_leaves_ambiguous_ones(self):
        incoming = self.root / "Incoming"
        incoming.mkdir()
        source = incoming / "Different.Movie.mp4"
        source.write_bytes(b"video")
        subtitle = incoming / "English.srt"
        subtitle.write_bytes(SRT)
        title = self.title | {"id": "tt456", "imdbId": "tt456", "title": "Different Movie"}
        target = Path(self.library.add(title, source, move=True))
        self.assertEqual(target.with_suffix(".srt").read_bytes(), SRT)
        self.assertFalse(subtitle.exists())

        another = incoming / "Next.Movie.mp4"
        another.write_bytes(b"video")
        for name in ("subtitle-a.srt", "subtitle-b.srt"):
            (incoming / name).write_bytes(SRT)
        next_target = Path(
            self.library.add(
                title | {"id": "tt789", "imdbId": "tt789", "title": "Next Movie"},
                another,
                move=True,
            )
        )
        self.assertFalse(next_target.with_suffix(".srt").exists())
        self.assertTrue((incoming / "subtitle-a.srt").exists())
        self.assertTrue((incoming / "subtitle-b.srt").exists())

    def test_subtitle_association_uses_episode_and_skips_ambiguous_fallback(self):
        folder = self.root / "Episodes"
        folder.mkdir()
        first, second = (folder / f"Show.S01E{episode:02d}.mkv" for episode in (1, 2))
        for video in (first, second):
            video.write_bytes(b"video")
        matching = folder / "Different.Release.S01E02.en.srt"
        unmatched = folder / "unknown.srt"
        matching.write_bytes(SRT)
        unmatched.write_bytes(SRT)
        assigned = subtitle_associations([first, second], [matching, unmatched])
        self.assertEqual(assigned[first], [])
        self.assertEqual(assigned[second], [(matching, ".en")])

    def test_import_refuses_subtitle_collision_before_moving_video(self):
        incoming = self.root / "Incoming"
        incoming.mkdir()
        source = incoming / "Collision.Movie.mp4"
        subtitle = incoming / "Collision.Movie.srt"
        source.write_bytes(b"video")
        subtitle.write_bytes(SRT)
        title = self.title | {"id": "tt456", "imdbId": "tt456", "title": "Collision Movie"}
        target = self.root / "Videos/Movies/Collision Movie (2025)/Collision Movie (2025).mp4"
        target.parent.mkdir(parents=True)
        target.with_suffix(".srt").write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "subtitle already exists"):
            self.library.add(title, source, move=True)
        self.assertTrue(source.exists())
        self.assertTrue(subtitle.exists())
        self.assertEqual(target.with_suffix(".srt").read_bytes(), b"keep")

    def test_import_writes_release_to_movie_nfo_and_preserves_existing_nfo(self):
        nfo = self.video.parent / "movie.nfo"
        release = ET.parse(nfo).getroot().find("moviesrelease")
        self.assertEqual(release.findtext("name"), "Example 1080p WEB-DL")
        self.assertEqual(release.findtext("originalfilename"), "Example.2025.WEB-DL.mkv")
        self.assertEqual(release.findtext("source"), "Local")
        nfo.write_text("<movie><title>My edited title</title></movie>")
        self.library.add(self.title, self.video, release_name="New release")
        self.assertEqual(ET.parse(nfo).getroot().findtext("title"), "My edited title")
        sidecar = self.video.with_suffix(".release.nfo")
        self.assertEqual(
            ET.parse(sidecar).getroot().find("moviesrelease").findtext("name"), "New release"
        )
        self.assertEqual(
            self.backend.inspect({"path": str(self.video)})["release"]["name"], "New release"
        )

    def test_series_episode_gets_own_release_nfo(self):
        show = {"kind": "tv", "id": "tt456", "imdbId": "tt456", "title": "A Show", "year": 2020}
        source = self.root / "A.Show.S01E02.mkv"
        source.write_bytes(b"video")
        path = Path(self.library.add(show, source, move=True, release_name="A Show S01 WEB-DL"))
        self.assertTrue((path.parent.parent / "tvshow.nfo").is_file())
        release = ET.parse(path.with_suffix(".release.nfo")).getroot()
        self.assertEqual(release.findtext("season"), "1")
        self.assertEqual(release.findtext("episode"), "2")
        self.assertEqual(release.find("moviesrelease").findtext("name"), "A Show S01 WEB-DL")

    def test_inventory_lists_sidecars_and_embedded_tracks(self):
        sidecar = self.video.with_name(self.video.stem + ".bg.srt")
        sidecar.write_bytes(SRT)
        release_sidecar = self.video.parent / "Example.2025.WEB-DL.vie.srt"
        release_sidecar.write_bytes(SRT)
        (self.video.parent / "trailer.mp4").write_bytes(b"extra")
        with patch.object(
            self.backend,
            "probe",
            return_value=(
                23.976,
                [
                    {
                        "index": 2,
                        "language": "vi",
                        "codec": "subrip",
                        "title": "Vietnamese",
                        "forced": False,
                        "extractable": True,
                    }
                ],
            ),
        ):
            result = self.backend.inspect({"path": str(self.video)})
        self.assertEqual(result["fps"], 23.976)
        self.assertEqual({item["language"] for item in result["files"]}, {"bg", "vi"})
        self.assertTrue(all(not item["managed"] for item in result["files"]))
        self.assertEqual(result["embedded"][0]["language"], "vi")
        self.assertEqual(result["languages"], ["en"])
        with self.assertRaises(SubtitleError):
            self.backend.remove({"path": str(self.video), "subtitle": str(sidecar)})

    def test_series_sidecars_follow_episode_number(self):
        show = {"kind": "tv", "id": "tt456", "imdbId": "tt456", "title": "A Show", "year": 2020}
        paths = []
        for episode in (2, 3):
            source = self.root / f"A.Show.S01E{episode:02d}.mkv"
            source.write_bytes(b"video")
            paths.append(Path(self.library.add(show, source, move=True)))
        good = paths[0].parent / "A.Show.2020.S01E02.en.srt"
        bad = paths[0].parent / "A.Show.2020.S01E03.bg.srt"
        good.write_bytes(SRT)
        bad.write_bytes(SRT)
        files = self.backend.inspect({"path": str(paths[0])})["files"]
        self.assertEqual([item["name"] for item in files], [good.name])

    def test_search_three_languages_downloads_separate_sidecars_and_retimes(self):
        with patch.object(self.backend, "probe", return_value=(23.976, [])):
            found = self.backend.search({"path": str(self.video), "languages": ["bg", "vi", "en"]})
            self.assertEqual([row["language"] for row in found["items"]], ["bg", "vi", "en"])
            self.assertTrue(all(row["hashMatch"] for row in found["items"]))
            self.assertEqual(self.client.calls[1][1]["imdb_id"], "123")
            paths = [
                Path(
                    self.backend.download(
                        {
                            "path": str(self.video),
                            "fileId": row["fileId"],
                            "searchId": found["searchId"],
                            "adapt": True,
                        }
                    )["path"]
                )
                for row in found["items"]
            ]
        self.assertEqual(
            [path.name for path in paths],
            [self.video.stem + "." + code + ".srt" for code in ("bg", "vi", "en")],
        )
        self.assertIn("00:00:26,068", paths[0].read_text())
        inventory = self.backend.inspect({"path": str(self.video)})
        self.assertTrue(all(item["managed"] for item in inventory["files"]))
        self.backend.remove({"path": str(self.video), "subtitle": str(paths[0])})
        self.assertFalse(paths[0].exists())
        self.assertTrue(paths[1].exists())

    def test_adjust_replaces_sidecar_and_keeps_numbered_backups(self):
        original = self.video.with_name(self.video.stem + ".en.srt")
        before = SRT + b"At 00:00:25,000 we leave.\n"
        original.write_bytes(before)
        with patch.object(self.backend, "probe", return_value=(25, [])):
            first = self.backend.retime(
                {"path": str(self.video), "subtitle": str(original), "sourceFps": 24, "offset": 1}
            )
            after_first = original.read_bytes()
            second = self.backend.retime(
                {"path": str(self.video), "subtitle": str(original), "sourceFps": 25, "offset": 1}
            )
        self.assertEqual(first["path"], str(original))
        self.assertEqual(first["backup"], str(original) + ".bak")
        self.assertEqual(Path(first["backup"]).read_bytes(), before)
        self.assertEqual(second["backup"], str(original) + ".bak.2")
        self.assertEqual(Path(second["backup"]).read_bytes(), after_first)
        self.assertIn("At 00:00:25,000 we leave.", original.read_text())
        self.assertIn("00:00:25,000 -->", after_first.decode())
        self.assertIn("--> 00:00:26,920", after_first.decode())
        self.assertEqual(
            [item["path"] for item in self.backend.inspect({"path": str(self.video)})["files"]],
            [str(original)],
        )

    def test_adjust_does_not_change_a_hard_linked_source(self):
        original = self.video.with_name(self.video.stem + ".en.srt")
        original.write_bytes(SRT)
        source = self.root / "seeding.srt"
        os.link(original, source)
        with patch.object(self.backend, "probe", return_value=(25, [])):
            result = self.backend.retime(
                {"path": str(self.video), "subtitle": str(original), "sourceFps": 25, "offset": 1}
            )
        self.assertEqual(source.read_bytes(), SRT)
        self.assertTrue(os.path.samefile(source, result["backup"]))
        self.assertFalse(os.path.samefile(source, original))

    def test_adjust_keeps_original_if_replacement_fails(self):
        original = self.video.with_name(self.video.stem + ".en.srt")
        original.write_bytes(SRT)
        with (
            patch.object(self.backend, "probe", return_value=(25, [])),
            patch("spaces.movies.subtitle_backend.os.replace", side_effect=OSError("disk failure")),
        ):
            with self.assertRaises(SubtitleError):
                self.backend.retime(
                    {
                        "path": str(self.video),
                        "subtitle": str(original),
                        "sourceFps": 25,
                        "offset": 1,
                    }
                )
        self.assertEqual(original.read_bytes(), SRT)
        self.assertFalse(Path(str(original) + ".bak").exists())
        self.assertFalse(list(original.parent.glob(".movies-sub-*")))

    def test_unregistered_video_and_unsearched_download_are_rejected(self):
        with self.assertRaises(SubtitleError):
            self.backend.inspect({"path": str(self.root / "not-local.mkv")})
        with self.assertRaises(SubtitleError):
            self.backend.download({"path": str(self.video), "fileId": 10})

    def test_selected_sidecar_launches_mpv_with_that_language(self):
        sidecar = self.video.with_name(self.video.stem + ".vi.srt")
        sidecar.write_bytes(SRT)
        with patch("spaces.movies.subtitle_backend.shutil.which", return_value="/usr/bin/mpv"):
            result = self.backend.play_with({"path": str(self.video), "subtitle": str(sidecar)})
        self.assertEqual(
            result["command"], ["mpv", "--sub-file=" + str(sidecar), "--", str(self.video)]
        )

    def test_deleting_local_video_clears_generated_subtitle_record(self):
        found = self.backend.search({"path": str(self.video), "languages": ["bg"]})
        sidecar = Path(
            self.backend.download(
                {"path": str(self.video), "fileId": 10, "searchId": found["searchId"]}
            )["path"]
        )
        self.library.remove([str(self.video)])
        self.assertFalse(sidecar.exists())
        with closing(sqlite3.connect(self.data / "library.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM subtitle_managed").fetchone()[0], 0)

    def test_extract_embedded_text_track_as_sidecar(self):
        track = {
            "index": 2,
            "language": "vi",
            "codec": "subrip",
            "title": "",
            "forced": False,
            "extractable": True,
        }

        def ffmpeg(args, **kwargs):
            self.assertEqual(args[args.index("-map") + 1], "0:2")
            Path(args[-1]).write_bytes(SRT)
            return SimpleNamespace(returncode=0)

        with (
            patch.object(self.backend, "probe", return_value=(23.976, [track])),
            patch("spaces.movies.subtitle_backend.subprocess.run", side_effect=ffmpeg),
        ):
            result = self.backend.extract({"path": str(self.video), "index": 2})
        self.assertTrue(Path(result["path"]).is_file())
        self.assertTrue(result["path"].endswith(".embedded.vi.srt"))

    def test_moviehash_uses_first_and_last_64k(self):
        size = self.video.stat().st_size
        block = int.from_bytes(b"12345678", "little")
        self.assertEqual(
            moviehash(self.video), f"{(size + block * 16384) & 0xFFFFFFFFFFFFFFFF:016x}"
        )

    def test_episode_search_uses_series_identity_and_episode_numbers(self):
        show = {"kind": "tv", "id": "tt456", "imdbId": "tt456", "title": "A Show", "year": 2020}
        source = self.root / "A.Show.S01E02.mkv"
        source.write_bytes(b"12345678" * 17000)
        video = self.library.add(show, source, move=True)
        result = self.backend.search({"path": video, "languages": ["bg"]})
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(self.client.calls[-1][1]["parent_imdb_id"], "456")
        self.assertEqual(self.client.calls[-1][1]["season_number"], 1)
        self.assertEqual(self.client.calls[-1][1]["episode_number"], 2)

    def test_more_results_keep_first_page_downloadable(self):
        class Paged(FakeOpenSubtitles):
            def request(self, path, params=None, **kwargs):
                result = super().request(path, params, **kwargs)
                if params.get("page") == 2:
                    result["data"][0]["attributes"]["files"][0]["file_id"] = 40
                result["total_pages"] = 2
                return result

        self.backend.client_override = Paged()
        first = self.backend.search({"path": str(self.video), "languages": ["bg"]})
        self.assertEqual(first["nextPage"], 2)
        second = self.backend.search(
            {"path": str(self.video), "languages": ["bg"], "page": 2, "searchId": first["searchId"]}
        )
        self.assertEqual([row["fileId"] for row in second["items"]], [40])
        for file_id in (10, 40):
            result = self.backend.download(
                {"path": str(self.video), "fileId": file_id, "searchId": first["searchId"]}
            )
            self.assertTrue(Path(result["path"]).is_file())

    def test_download_requires_account_credentials(self):
        with self.assertRaisesRegex(SubtitleError, "username and password"):
            OpenSubtitles({"api_key": "test"}).download(10)

    def test_opensubtitles_login_download_protocol(self):
        class Response(io.BytesIO):
            def __init__(self, content, url):
                super().__init__(content)
                self.url = url

            def geturl(self):
                return self.url

        calls = []

        def urlopen(request, timeout):
            calls.append(request)
            if request.full_url.endswith("/login"):
                return Response(
                    json.dumps(
                        {"base_url": "api.opensubtitles.com", "token": "test-token"}
                    ).encode(),
                    request.full_url,
                )
            if request.full_url.endswith("/download"):
                return Response(
                    json.dumps(
                        {"link": "https://www.opensubtitles.com/download/test.srt", "remaining": 17}
                    ).encode(),
                    request.full_url,
                )
            return Response(SRT, request.full_url)

        with patch("spaces.movies.subtitle_backend.urllib.request.urlopen", side_effect=urlopen):
            payload, remaining = OpenSubtitles(
                {"api_key": "key", "username": "user", "password": "password"}
            ).download(10)
        self.assertEqual(payload, SRT)
        self.assertEqual(remaining, 17)
        self.assertEqual(json.loads(calls[1].data)["file_id"], 10)
        self.assertEqual(calls[1].get_header("Authorization"), "Bearer test-token")
        self.assertEqual(calls[0].get_header("Api-key"), "key")


if __name__ == "__main__":
    unittest.main()
