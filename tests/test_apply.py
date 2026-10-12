import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]

class HomeTests(unittest.TestCase):
    def publish(self, staging, home, check=True):
        return subprocess.run(['python3', str(REPO / 'scripts/publish-home.py'),
                               str(staging), str(home), str(os.getuid()), str(os.getgid())],
                              check=check, text=True, capture_output=True)

    def test_links_generated_files_and_preserves_omitted_outputs(self):
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
            self.publish(stage, home)
            self.assertEqual((home / '.config/generated.conf').read_text(), 'generated\n')
            generated.unlink()
            link.unlink()
            self.publish(stage, home)
            self.assertTrue((home / '.config/plain.conf').exists())
            self.assertEqual((home / '.config/generated.conf').read_text(), 'generated\n')
            self.assertFalse((home / '.local/state/system-config').exists())
            self.assertEqual(config.read_text(), 'plain\n')

    def test_rejects_parent_links_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, stage, outside = [root / name for name in ('home', 'stage', 'outside')]
            home.mkdir()
            outside.mkdir()
            (home / '.config').symlink_to(outside)
            (stage / '.config').mkdir(parents=True)
            (stage / '.config/app.conf').write_text('new\n')
            result = self.publish(stage, home, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(outside.iterdir()), [])

    def test_mpv_rebuilds_regular_files_without_accumulating_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / 'pack.json'
            pack.write_text(json.dumps({'setting-groups': {'quality': {'settings': [['scale', 'ewa_lanczos']], 'shaders': ['FSR.glsl']}},
                                       'profiles': {'generic-high': {'setting-groups': ['quality']}, 'example': {'shaders': ['CAS.glsl']}}}))
            env = dict(os.environ, HOME=str(root / 'home'), DOTFILES_REPO=str(REPO), MPV_SHADER_PACK=str(pack))
            hook = REPO / 'modules/media/video/mpv/scripts/50_mpv.sh'
            for filename in ('mpv.conf', 'input.conf'):
                destination = root / 'home/.config/mpv' / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.unlink(missing_ok=True)
                destination.symlink_to(REPO / 'modules/media/video/mpv/files/home/.config/mpv' / filename)
            subprocess.run(['bash', str(hook)], env=env, check=True, capture_output=True)
            config = root / 'home/.config/mpv/mpv.conf'
            initial = config.read_text()
            self.assertEqual(initial.count('[generic-high]'), 1)
            self.assertIn('profile=generic-high', initial)
            self.assertIn('scale=ewa_lanczos', initial)
            self.assertFalse(config.is_symlink())
            config.write_text('drift\n')
            for filename in ('mpv.conf', 'input.conf'):
                destination = root / 'home/.config/mpv' / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.unlink(missing_ok=True)
                destination.symlink_to(REPO / 'modules/media/video/mpv/files/home/.config/mpv' / filename)
            subprocess.run(['bash', str(hook)], env=env, check=True, capture_output=True)
            self.assertEqual(config.read_text(), initial)

class NativeConfigTests(unittest.TestCase):
    def test_package_fragments_use_native_names(self):
        for fragment in REPO.glob('modules/**/config.json'):
            for package in json.loads(fragment.read_text()).get('packages', []):
                self.assertNotIn(':', package, str(fragment))
                if '/' in package:
                    self.assertIn(package.split('/')[0], ('core', 'extra', 'multilib', 'ogc', 'chaotic-aur'))
        self.assertFalse((REPO / 'lib/module.sh').exists())
        self.assertFalse((REPO / 'scripts/module-runtime.sh').exists())

if __name__ == '__main__':
    unittest.main()
