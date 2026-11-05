"""Interrupted and racing imports never expose partial movies or replace files."""

import errno
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.movies import local


class MovieImportTests(unittest.TestCase):
    def test_failed_cross_filesystem_copy_preserves_source_and_cleans_partial_file(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'incoming.mkv', root / 'movie.mkv'
            source.write_bytes(b'complete movie')

            def interrupted_copy(source, temporary):
                Path(temporary).write_bytes(b'partial')
                raise OSError('interrupted copy')

            with (
                patch.object(
                    local.os, 'link', side_effect=OSError(errno.EXDEV, 'cross-device')
                ),
                patch.object(local.shutil, 'copy2', side_effect=interrupted_copy),
            ):
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

    def test_cross_filesystem_import_copy_is_hidden_and_removed_on_close(self):
        # Books downloads and music torrent imports copy rather than move.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'staging/The.General.1926.mkv'
            source.parent.mkdir()
            source.write_bytes(b'complete movie')
            title = {'kind': 'movie', 'id': 'tt0017925', 'title': 'The General'}
            title['year'] = 1926
            real_link, copies = os.link, []

            def link(src, dst):
                if Path(src) == source:
                    raise OSError(errno.EXDEV, 'cross-device')
                return real_link(src, dst)

            def copy(src, dst):
                copies.append((Path(dst), Path(dst) in local._transfers))
                Path(dst).write_bytes(Path(src).read_bytes())

            with (
                patch.dict(os.environ, {'XDG_VIDEOS_DIR': str(root / 'Videos')}),
                patch.object(local.os, 'link', side_effect=link),
                patch.object(local.shutil, 'copy2', side_effect=copy),
            ):
                target = Path(local.LocalLibrary(root / 'data').add(title, source))
            temporary, tracked = copies[0]
            self.assertTrue(tracked)
            self.assertTrue(temporary.name.startswith('.movies-import-'))
            self.assertEqual(temporary.parent, target.parent)
            self.assertFalse(temporary.exists())
            self.assertFalse(local._transfers)
            self.assertEqual(target.read_bytes(), b'complete movie')
            self.assertEqual(source.read_bytes(), b'complete movie')

    def test_removal_never_selects_a_linked_library_root(self):
        # A restored or legacy row may name a file directly in the library root.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            movies = root / 'media/Videos/Movies'
            kept = movies / 'Kept (2020)/Kept (2020).mkv'
            kept.parent.mkdir(parents=True)
            kept.write_bytes(b'unrelated movie')
            stray = movies / 'Stray.mkv'
            stray.write_bytes(b'stray movie')
            (root / 'Videos').symlink_to(root / 'media/Videos')
            linked = root / 'Videos/Movies/Stray.mkv'
            with patch.dict(os.environ, {'XDG_VIDEOS_DIR': str(root / 'Videos')}):
                library = local.LocalLibrary(root / 'data')
                with library.db() as db:
                    db.execute(
                        'INSERT INTO local_files VALUES (?,?,?,?,?,?)',
                        ('movie', 'tt1', 0, 0, str(linked), json.dumps({})),
                    )
                with self.assertRaisesRegex(ValueError, 'unsafe'):
                    library.remove([str(linked)])
            self.assertEqual(kept.read_bytes(), b'unrelated movie')
            self.assertTrue(stray.exists())

    def test_filesystems_without_hard_links_publish_by_exclusive_rename(self):
        # vfat and exFAT refuse link(); renameat2(RENAME_NOREPLACE) still
        # publishes atomically without replacing anything.
        unsupported = OSError(errno.EPERM, 'hard links unsupported')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'incoming.mkv', root / 'movie.mkv'
            source.write_bytes(b'complete movie')
            with (
                patch.object(local.os, 'link', side_effect=unsupported),
                patch.object(local.shutil, 'copy2') as copy,
            ):
                local.move_file(source, target)
                self.assertFalse(copy.called)
            self.assertFalse(source.exists())
            self.assertEqual(target.read_bytes(), b'complete movie')

            copied = root / 'copy.mkv'
            with patch.object(local.os, 'link', side_effect=unsupported):
                local.publish(target, copied)
            self.assertEqual(copied.read_bytes(), b'complete movie')
            self.assertEqual(target.read_bytes(), b'complete movie')
            self.assertFalse(list(root.glob('.movies-import-*')))

            other = root / 'other.mkv'
            other.write_bytes(b'other movie')
            with patch.object(local.os, 'link', side_effect=unsupported):
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    local.move_file(other, target)
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    local.publish(other, copied)
            self.assertEqual(other.read_bytes(), b'other movie')
            self.assertEqual(target.read_bytes(), b'complete movie')
            self.assertEqual(copied.read_bytes(), b'complete movie')
            self.assertFalse(list(root.glob('.movies-import-*')))
