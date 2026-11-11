import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class HomeTests(unittest.TestCase):
    def publish(self, staging, home, check=True):
        return subprocess.run(
            [
                'python3',
                str(REPO / 'scripts/publish-home.py'),
                str(staging),
                str(home),
                str(os.getuid()),
                str(os.getgid()),
            ],
            check=check,
            text=True,
            capture_output=True,
        )

    def test_links_generated_files_preserve_local_edits_and_remove_clean_omitted_outputs(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, stage = root / 'home', root / 'stage'
            home.mkdir()
            (stage / '.config').mkdir(parents=True)
            (stage / '.local/state/bash').mkdir(parents=True)
            config = root / 'plain.conf'
            config.write_text('plain\n')
            link = stage / '.config/plain.conf'
            link.symlink_to(config)
            generated = stage / '.config/generated.conf'
            generated.write_text('generated\n')
            self.publish(stage, home)
            self.assertEqual((home / '.config/plain.conf').resolve(), config)
            self.assertFalse((home / '.config/generated.conf').is_symlink())
            self.assertTrue((home / '.local/state/bash').is_dir())
            (home / '.config/generated.conf').write_text('drift\n')
            result = self.publish(stage, home, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertEqual((home / '.config/generated.conf').read_text(), 'drift\n')
            (home / '.config/generated.conf').write_text('generated\n')
            generated.unlink()
            link.unlink()
            self.publish(stage, home)
            self.assertFalse((home / '.config/plain.conf').exists())
            self.assertFalse((home / '.config/generated.conf').exists())
            self.assertEqual(config.read_text(), 'plain\n')

    def test_rejects_parent_links_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, stage, outside = [
                root / name for name in ('home', 'stage', 'outside')
            ]
            home.mkdir()
            outside.mkdir()
            (home / '.config').symlink_to(outside)
            (stage / '.config').mkdir(parents=True)
            (stage / '.config/app.conf').write_text('new\n')
            result = self.publish(stage, home, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
