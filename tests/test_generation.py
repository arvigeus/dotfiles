import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class GenerationTests(unittest.TestCase):
    def test_hosts_share_storage_except_device_and_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for name in ('scripts', 'modules'):
                shutil.copytree(REPO / name, repo / name)
            shutil.copy(REPO / 'generate-config.py', repo)
            def generate(host, answers='', configure=False):
                command = ['python3', str(repo / 'generate-config.py'), host]
                if configure:
                    command.append('--configure')
                return subprocess.run(command, input=answers,
                                      text=True, capture_output=True)
            result = generate('zephyrus')
            self.assertEqual(result.returncode, 0, result.stderr)
            zephyrus = json.loads((repo / 'user-configuration.json').read_text())
            result = generate('vm', '\n10\n')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('at least 52 GiB', result.stderr)
            self.assertEqual(json.loads((repo / 'user-configuration.json').read_text()), zephyrus)
            result = generate('vm', '\n64\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            vm = json.loads((repo / 'user-configuration.json').read_text())
            self.assertEqual(generate('vm').returncode, 0)
            self.assertEqual(json.loads((repo / 'user-configuration.json').read_text()), vm)
            result = generate('vm', '/dev/sda\n80\n', configure=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = json.loads((repo / 'user-configuration.json').read_text())
            self.assertEqual(updated['disk_config']['device_modifications'][0]['device'], '/dev/sda')
            self.assertEqual(vm['bootloader_config'], zephyrus['bootloader_config'])
            self.assertIn('udisks2', vm['packages'])
            for config, device in ((zephyrus, '/dev/nvme0n1'), (vm, '/dev/vda')):
                disk = config['disk_config']['device_modifications'][0]
                self.assertEqual(disk.pop('device'), device)
                disk['partitions'][1]['size'].pop('value')
            self.assertEqual(vm['disk_config'], zephyrus['disk_config'])

    def test_named_fragments_share_packages_but_isolate_host_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / 'scripts').mkdir()
            shutil.copy(REPO / 'generate-config.py', repo)
            shutil.copy(REPO / 'scripts/select-modules.sh', repo / 'scripts')
            (repo / 'host').write_text('zephyrus\n')
            for host in ('zephyrus', 'vm'):
                path = repo / 'modules/hosts' / host
                path.mkdir(parents=True)
                (path / 'config.json').write_text(json.dumps({'hostname': host}))
            (repo / 'modules/hosts/zephyrus/storage.jsonc').write_text(
                '// Host-specific disk\n{"disk_config": {"config_type": "default_layout"}}')
            shared = repo / 'modules/hardware/storage'
            shared.mkdir(parents=True)
            (shared / 'packages.json').write_text('{"packages": ["udisks2"]}')
            assets = shared / 'files/home/.config/example'
            assets.mkdir(parents=True)
            (assets / 'storage.jsonc').write_text('{"packages": ["app-data"]}')
            for host in ('zephyrus', 'vm'):
                subprocess.run(['python3', str(repo / 'generate-config.py')],
                               env=dict(os.environ, DOTFILES_HOST=host),
                               check=True, capture_output=True)
                generated = json.loads((repo / 'user-configuration.json').read_text())
                self.assertEqual(generated['packages'], ['udisks2'])
                self.assertEqual('disk_config' in generated, host == 'zephyrus')

    def test_files_category_is_discovered_and_assets_are_not_configs(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / 'scripts').mkdir()
            shutil.copy(REPO / 'generate-config.py', repo)
            shutil.copy(REPO / 'scripts/select-modules.sh', repo / 'scripts')
            (repo / 'host').write_text('zephyrus\n')
            host = repo / 'modules/hosts/zephyrus'
            host.mkdir(parents=True)
            (host / 'config.json').write_text('{"hostname": "zephyrus"}')
            dolphin = repo / 'modules/files/dolphin'
            dolphin.mkdir(parents=True)
            (dolphin / 'config.json').write_text('{"packages": ["kio-admin"]}')
            assets = dolphin / 'files/home/.config/example'
            assets.mkdir(parents=True)
            (assets / 'config.json').write_text('{"packages": ["app-data"]}')
            env = dict(os.environ, DOTFILES_HOST='zephyrus')
            subprocess.run(['python3', str(repo / 'generate-config.py')],
                           env=env, check=True, capture_output=True)
            generated = json.loads((repo / 'user-configuration.json').read_text())
            self.assertEqual(generated['packages'], ['kio-admin'])


if __name__ == '__main__':
    unittest.main()
