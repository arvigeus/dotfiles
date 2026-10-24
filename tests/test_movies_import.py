"""Interrupted and racing imports never expose partial movies or replace files."""
import errno
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import support
sys.path.insert(0, str(support.DESKTOP))
from spaces.movies import local


class MovieImportTests(unittest.TestCase):
    def test_failed_cross_filesystem_copy_preserves_source_and_cleans_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'incoming.mkv', root / 'movie.mkv'
            source.write_bytes(b'complete movie')
            def interrupted_copy(source, temporary):
                Path(temporary).write_bytes(b'partial')
                raise OSError('interrupted copy')
            with patch.object(local.os, 'link', side_effect=OSError(errno.EXDEV, 'cross-device')), \
                    patch.object(local.shutil, 'copy2', side_effect=interrupted_copy):
                with self.assertRaisesRegex(OSError, 'interrupted'):
                    local.move_file(source, target)
            self.assertEqual(source.read_bytes(), b'complete movie')
            self.assertFalse(target.exists())
            self.assertFalse(list(root.glob('.movies-import-*')))

    def test_destination_collision_preserves_both_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.write_bytes(b'incoming')
            target.write_bytes(b'existing')
            with self.assertRaises(ValueError):
                local.move_file(source, target)
            self.assertEqual(source.read_bytes(), b'incoming')
            self.assertEqual(target.read_bytes(), b'existing')
