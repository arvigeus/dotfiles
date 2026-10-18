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
            backend = 'home/.config/devices/keyboard/backends/'
            zephyrus_links = {entry['target']: entry['source'] for entry in zephyrus['extra']['symlinks']}
            vm_links = {entry['target']: entry['source'] for entry in vm['extra']['symlinks']}
            self.assertTrue(zephyrus_links[backend + 'asus.py'].startswith('modules/hardware/devices/zephyrus/'))
            self.assertNotIn(backend + 'asus.py', vm_links)
            power_backend = 'home/.config/devices/power/backends/asus.py'
            self.assertTrue(zephyrus_links[power_backend].startswith('modules/hardware/devices/zephyrus/'))
            self.assertNotIn(power_backend, vm_links)
            for links in (zephyrus_links, vm_links):
                self.assertTrue(links[backend + 'logitech.py'].startswith('modules/hardware/peripherals/logitech/'))
                self.assertFalse(any(target.endswith('drawers/keyboard/lighting.py') or target.endswith('drawers/keyboard/logitech.py') for target in links))
            self.assertEqual(generate('vm').returncode, 0)
            self.assertEqual(json.loads((repo / 'user-configuration.json').read_text()), vm)
            result = generate('vm', '/dev/sda\n80\n', configure=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = json.loads((repo / 'user-configuration.json').read_text())
            self.assertEqual(updated['disk_config']['device_modifications'][0]['device'], '/dev/sda')
            self.assertEqual(vm['bootloader_config'], zephyrus['bootloader_config'])
            self.assertIn('udisks2', vm['packages'])
            self.assertIn('upower', vm['packages'])
            self.assertIn('upower.service', vm['services'])
            self.assertIn('power-source.service', zephyrus['services'])
            self.assertNotIn('power-source.service', vm['services'])
            power_files = {entry['target']: entry for entry in zephyrus['extra']['files']}
            self.assertEqual(power_files['/usr/local/libexec/power-source']['mode'], '0755')
            self.assertIn('/etc/systemd/system/power-source.service', power_files)
            for config, device in ((zephyrus, '/dev/nvme0n1'), (vm, '/dev/vda')):
                files = {entry['target']: entry for entry in config['extra']['files']}
                self.assertNotIn('/usr/local/libexec/desktop-cpu-boost', files)
                self.assertNotIn('/usr/share/polkit-1/actions/org.dotfiles.desktop.cpu-boost.policy', files)
                disk = config['disk_config']['device_modifications'][0]
                self.assertEqual(disk.pop('device'), device)
                disk['partitions'][1]['size'].pop('value')
            self.assertEqual(vm['disk_config'], zephyrus['disk_config'])

    def test_automatic_discovery_and_disabled_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / 'scripts').mkdir()
            shutil.copy(REPO / 'generate-config.py', repo)
            shutil.copytree(REPO / 'scripts', repo / 'scripts', dirs_exist_ok=True)
            (repo / 'host').write_text('vm\n')
            for name in ('first', 'second', 'disabled', 'hosts/vm'):
                module = repo / 'modules' / name
                module.mkdir(parents=True)
                (module / 'config.json').write_text(json.dumps({'packages': [name]}))
            (repo / 'modules/disabled/check.sh').write_text('exit 1\n')
            subprocess.run(['python3', str(repo / 'generate-config.py')], check=True, capture_output=True)
            config = json.loads((repo / 'user-configuration.json').read_text())
            self.assertEqual(config['packages'], ['first', 'hosts/vm', 'second'])

    def test_named_fragments_share_packages_but_isolate_host_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / 'scripts').mkdir()
            shutil.copy(REPO / 'generate-config.py', repo)
            shutil.copytree(REPO / 'scripts', repo / 'scripts', dirs_exist_ok=True)
            (repo / 'host').write_text('zephyrus\n')
            for host in ('zephyrus', 'vm'):
                path = repo / 'modules/hosts' / host
                path.mkdir(parents=True)
                (path / 'config.json').write_text(json.dumps({'hostname': host}))
                (path / 'check.sh').write_text(f'[[ $DOTFILES_HOST == {host} ]]\n')
            (repo / 'modules/hosts/zephyrus/storage.config.jsonc').write_text(
                '// Host-specific disk\n{"disk_config": {"config_type": "default_layout"}}')
            shared = repo / 'modules/hardware/storage'
            shared.mkdir(parents=True)
            (shared / 'packages.config.json').write_text('{"packages": ["udisks2"]}')
            (shared / 'package.json').write_text('{"name": "app", "private": true}')
            (shared / 'tsconfig.json').write_text('{"compilerOptions": {"strict": true}}')
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
                self.assertNotIn('name', generated)
                self.assertNotIn('compilerOptions', generated)

    def test_script_order_extra_merging_and_selection_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            shutil.copy(REPO / 'generate-config.py', repo)
            shutil.copytree(REPO / 'scripts', repo / 'scripts')
            (repo / 'host').write_text('vm\n')
            (repo / 'modules/hosts/vm').mkdir(parents=True)
            (repo / 'modules/hosts/vm/config.json').write_text('{"hostname": "vm"}')
            for module, filename, marker in (('aaa', '99_late.sh', 'late'), ('zzz', '00_early.sh', 'early')):
                path = repo / 'modules' / module
                (path / 'scripts').mkdir(parents=True)
                (path / 'scripts' / filename).write_text(f'echo {marker}\n')
                (path / 'config.json').write_text(json.dumps({'extra': {
                    'aur_packages': ['shared', module],
                    'flatpak': {'remotes': {'flathub': 'same-url'}}}}))
            command = ['python3', str(repo / 'generate-config.py')]
            subprocess.run(command, check=True, capture_output=True)
            output = repo / 'user-configuration.json'
            original = output.read_text()
            config = json.loads(original)
            self.assertIn('echo early', config['custom_commands'][1])
            self.assertIn('echo late', config['custom_commands'][2])
            self.assertEqual(config['extra']['aur_packages'], ['shared', 'aaa', 'zzz'])
            self.assertNotIn('postinstall', config['extra'])
            (repo / 'modules/aaa/check.sh').write_text('exit 2\n')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('selection failed (2)', result.stderr)
            self.assertEqual(output.read_text(), original)
            (repo / 'modules/aaa/check.sh').write_text('exit 0\n')
            (repo / 'modules/aaa/config.json').write_text('{"hostname": "conflicting"}')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('conflicting setting: hostname', result.stderr)
            self.assertEqual(output.read_text(), original)

    def test_unknown_option_does_not_replace_generated_config(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / 'scripts').mkdir()
            shutil.copy(REPO / 'generate-config.py', repo)
            shutil.copytree(REPO / 'scripts', repo / 'scripts', dirs_exist_ok=True)
            (repo / 'host').write_text('vm\n')
            host = repo / 'modules/hosts/vm'
            host.mkdir(parents=True)
            fragment = host / 'config.json'
            fragment.write_text('{"hostname": "vm"}')
            command = ['python3', str(repo / 'generate-config.py')]
            subprocess.run(command, check=True, capture_output=True)
            output = repo / 'user-configuration.json'
            original = output.read_text()
            fragment.write_text('{"hostname": "vm", "packges": ["git"]}')
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('unsupported archinstall options: packges', result.stderr)
            self.assertEqual(output.read_text(), original)

    def test_discovery_does_not_read_file_assets_as_configs(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / 'scripts').mkdir()
            shutil.copy(REPO / 'generate-config.py', repo)
            shutil.copytree(REPO / 'scripts', repo / 'scripts', dirs_exist_ok=True)
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
            unlisted = repo / 'modules/unlisted'
            unlisted.mkdir()
            (unlisted / 'check.sh').write_text('exit 1\n')
            (unlisted / 'config.json').write_text('{"packages": ["not-selected"]}')
            env = dict(os.environ, DOTFILES_HOST='zephyrus')
            subprocess.run(['python3', str(repo / 'generate-config.py')],
                           env=env, check=True, capture_output=True)
            generated = json.loads((repo / 'user-configuration.json').read_text())
            self.assertEqual(generated['packages'], ['kio-admin'])

    def test_files_and_symlinks_cannot_share_a_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            shutil.copy(REPO / 'generate-config.py', repo)
            shutil.copytree(REPO / 'scripts', repo / 'scripts')
            (repo / 'host').write_text('vm\n')
            host = repo / 'modules/hosts/vm'
            host.mkdir(parents=True)
            (host / 'config.json').write_text('{"hostname": "vm"}')
            for kind in ('files', 'symlinks'):
                asset = repo / 'modules/example' / kind / 'home/.config/shared.conf'
                asset.parent.mkdir(parents=True)
                asset.write_text('shared\n')
            result = subprocess.run(['python3', str(repo / 'generate-config.py')],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Multiple modules provide home/.config/shared.conf', result.stderr)
            self.assertFalse((repo / 'user-configuration.json').exists())

    def test_file_manifests_exclude_python_bytecode(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            shutil.copy(REPO / 'generate-config.py', repo)
            shutil.copytree(REPO / 'scripts', repo / 'scripts')
            (repo / 'host').write_text('vm\n')
            host = repo / 'modules/hosts/vm'
            host.mkdir(parents=True)
            (host / 'config.json').write_text('{"hostname": "vm"}')
            for kind in ('files', 'symlinks'):
                assets = repo / 'modules/example' / kind / 'home/.config' / kind
                for name in ('backend.py', 'backend.pyc', 'backend.pyo', '__pycache__/backend.cpython-314.pyc', '__pycache__/metadata.json'):
                    path = assets / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('test\n')
            subprocess.run(['python3', str(repo / 'generate-config.py')], check=True, capture_output=True)
            generated = json.loads((repo / 'user-configuration.json').read_text())
            for kind in ('files', 'symlinks'):
                self.assertEqual([entry['target'] for entry in generated['extra'][kind]],
                                 [f'home/.config/{kind}/backend.py'])


if __name__ == '__main__':
    unittest.main()
