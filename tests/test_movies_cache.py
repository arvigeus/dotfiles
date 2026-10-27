"""Artwork is reused across worker restarts, bounded, and safe on failed reads."""

import concurrent.futures
import io
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.movies import image_cache


class Response(io.BytesIO):
    headers = {'Content-Type': 'image/png'}


class ArtworkCacheTests(unittest.TestCase):
    def test_warm_fetch_and_new_worker_do_not_download_again(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = image_cache.ArtworkCache(directory)
            with patch.object(
                image_cache.urllib.request, 'urlopen', return_value=Response(b'fixture')
            ) as fetch:
                first = cache.fetch('https://example.invalid/image?private=value')
                self.assertEqual(
                    cache.fetch('https://example.invalid/image?private=value'), first
                )
                reopened = image_cache.ArtworkCache(directory)
                self.assertEqual(
                    reopened.fetch('https://example.invalid/image?private=value'), first
                )
                self.assertEqual(fetch.call_count, 1)
            files = list(Path(directory).glob('*.img'))
            self.assertEqual(len(files), 1)
            self.assertNotIn('private', files[0].name)
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(Path(directory).stat().st_mode & 0o777, 0o700)

    def test_simultaneous_duplicates_share_one_download(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = image_cache.ArtworkCache(directory)

            def respond(*args, **kwargs):
                time.sleep(0.05)
                return Response(b'fixture')

            with patch.object(
                image_cache.urllib.request, 'urlopen', side_effect=respond
            ) as fetch:
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                    paths = list(
                        pool.map(
                            lambda _: cache.fetch('https://example.invalid/shared'),
                            range(6),
                        )
                    )
                self.assertEqual(len(set(paths)), 1)
                self.assertEqual(fetch.call_count, 1)

    def test_retention_and_lru_limits_only_remove_artwork(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = image_cache.ArtworkCache(directory, max_files=2, max_bytes=100)

            def respond(*args, **kwargs):
                return Response(b'fixture')

            with patch.object(
                image_cache.urllib.request, 'urlopen', side_effect=respond
            ):
                first = Path(
                    cache.fetch('https://example.invalid/one').removeprefix('file://')
                )
                os.utime(first, (time.time() - 120, time.time() - 120))
                second = Path(
                    cache.fetch('https://example.invalid/two').removeprefix('file://')
                )
                third = Path(
                    cache.fetch('https://example.invalid/three').removeprefix('file://')
                )
            self.assertFalse(first.exists())
            self.assertTrue(second.exists() and third.exists())
            unrelated = Path(directory) / 'library.sqlite'
            unrelated.write_text('personal data')
            os.utime(second, (0, 0))
            cache.prune()
            self.assertFalse(second.exists())
            self.assertEqual(unrelated.read_text(), 'personal data')
            cache.max_bytes = 1
            cache.prune()
            self.assertFalse(third.exists())

    def test_failed_download_cleans_partial_file(self):
        class Interrupted(Response):
            def read(self, size=-1):
                raise OSError('interrupted')

        with tempfile.TemporaryDirectory() as directory:
            cache = image_cache.ArtworkCache(directory)
            with patch.object(
                image_cache.urllib.request,
                'urlopen',
                return_value=Interrupted(b'fixture'),
            ):
                with self.assertRaises(image_cache.ImageError):
                    cache.fetch('https://example.invalid/image')
            self.assertFalse(list(Path(directory).iterdir()))

    def test_invalid_or_nonimage_responses_are_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = image_cache.ArtworkCache(directory)
            for url in (
                'file:///etc/passwd',
                'https://name:password@example.invalid/a',
            ):
                with self.assertRaises(image_cache.ImageError):
                    cache.fetch(url)
            response = Response(b'not an image')
            response.headers = {'Content-Type': 'text/html'}
            with patch.object(
                image_cache.urllib.request, 'urlopen', return_value=response
            ):
                with self.assertRaises(image_cache.ImageError):
                    cache.fetch('https://example.invalid/a')
            self.assertFalse(list(Path(directory).iterdir()))
