import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class GenerationTests(unittest.TestCase):
    def test_host_settings_are_reused_and_failed_reconfiguration_preserves_output(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for name in ('scripts', 'modules'):
                shutil.copytree(REPO / name, repo / name)
            shutil.copy(REPO / 'generate-config.py', repo)
            output = repo / 'user-configuration.json'

            def generate(host, answers='', configure=False):
                command = ['python3', str(repo / 'generate-config.py'), host]
                if configure:
                    command.append('--configure')
                return subprocess.run(
                    command, input=answers, text=True, capture_output=True
                )

            result = generate('zephyrus')
            self.assertEqual(result.returncode, 0, result.stderr)
            previous = output.read_bytes()
            result = generate('vm', '\n10\n')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('at least 52 GiB', result.stderr)
            self.assertEqual(output.read_bytes(), previous)

            result = generate('vm', '\n64\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            vm = json.loads(output.read_text())
            result = generate('vm')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text()), vm)

            result = generate('vm', '/dev/sda\n80\n', configure=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = json.loads(output.read_text())
            self.assertEqual(
                updated['disk_config']['device_modifications'][0]['device'], '/dev/sda'
            )

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
            subprocess.run(
                ['python3', str(repo / 'generate-config.py')],
                check=True,
                capture_output=True,
            )
            config = json.loads((repo / 'user-configuration.json').read_text())
            self.assertEqual(config['packages'], ['first', 'hosts/vm', 'second'])

    def test_only_module_fragments_are_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / 'scripts').mkdir()
            shutil.copy(REPO / 'generate-config.py', repo)
            (repo / 'host').write_text('zephyrus\n')
            for host in ('zephyrus', 'vm'):
                path = repo / 'modules/hosts' / host
                path.mkdir(parents=True)
                (path / 'config.json').write_text(json.dumps({'hostname': host}))
                (path / 'check.sh').write_text(f'[[ $DOTFILES_HOST == {host} ]]\n')
            (repo / 'modules/hosts/zephyrus/config.jsonc').write_text(
                '// Host-specific disk\n{"disk_config": {"config_type": "default_layout",},}'
            )
            shared = repo / 'modules/hardware/storage'
            shared.mkdir(parents=True)
            (shared / 'config.json').write_text('{"packages": ["udisks2"]}')
            (shared / 'packages.config.json').write_text(
                '{"packages": ["not-a-fragment"]}'
            )
            (shared / 'package.json').write_text('{"name": "app", "private": true}')
            assets = shared / 'files/home/.config/example'
            assets.mkdir(parents=True)
            (assets / 'config.jsonc').write_text('{"packages": ["app-data"]}')
            (assets / 'config.json').write_text('{"packages": ["app-data"]}')
            for host in ('zephyrus', 'vm'):
                subprocess.run(
                    ['python3', str(repo / 'generate-config.py')],
                    env=dict(os.environ, DOTFILES_HOST=host),
                    check=True,
                    capture_output=True,
                )
                generated = json.loads((repo / 'user-configuration.json').read_text())
                self.assertEqual(generated['packages'], ['udisks2'])
                self.assertEqual('disk_config' in generated, host == 'zephyrus')
                self.assertNotIn('name', generated)

    def test_script_order_extra_merging_and_selection_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            shutil.copy(REPO / 'generate-config.py', repo)
            shutil.copytree(REPO / 'scripts', repo / 'scripts')
            (repo / 'host').write_text('vm\n')
            (repo / 'modules/hosts/vm').mkdir(parents=True)
            (repo / 'modules/hosts/vm/config.json').write_text('{"hostname": "vm"}')
            for module, filename, marker in (
                ('aaa', '99_late.sh', 'late'),
                ('zzz', '00_early.sh', 'early'),
            ):
                path = repo / 'modules' / module
                (path / 'scripts').mkdir(parents=True)
                (path / 'scripts' / filename).write_text(f'echo {marker}\n')
                (path / 'config.json').write_text(
                    json.dumps(
                        {
                            'extra': {
                                'aur_packages': ['shared', module],
                                'cargo_packages': ['tokei', module],
                                'flatpak': {'remotes': {'flathub': 'same-url'}},
                            }
                        }
                    )
                )
            command = ['python3', str(repo / 'generate-config.py')]
            subprocess.run(command, check=True, capture_output=True)
            output = repo / 'user-configuration.json'
            original = output.read_text()
            config = json.loads(original)
            self.assertEqual(
                config['extra']['scripts'],
                ['modules/zzz/scripts/00_early.sh', 'modules/aaa/scripts/99_late.sh'],
            )
            self.assertEqual(len(config['custom_commands']), 1)
            self.assertEqual(config['extra']['aur_packages'], ['shared', 'aaa', 'zzz'])
            self.assertEqual(config['extra']['cargo_packages'], ['tokei', 'aaa', 'zzz'])
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
            result = subprocess.run(
                ['python3', str(repo / 'generate-config.py')],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                'Multiple modules provide home/.config/shared.conf', result.stderr
            )
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
                for name in (
                    'backend.py',
                    'backend.pyc',
                    'backend.pyo',
                    '__pycache__/backend.cpython-314.pyc',
                    '__pycache__/metadata.json',
                ):
                    path = assets / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('test\n')
            subprocess.run(
                ['python3', str(repo / 'generate-config.py')],
                check=True,
                capture_output=True,
            )
            generated = json.loads((repo / 'user-configuration.json').read_text())
            for kind in ('files', 'symlinks'):
                self.assertEqual(
                    [entry['target'] for entry in generated['extra'][kind]],
                    [f'home/.config/{kind}/backend.py'],
                )

    def test_invalid_explicit_assets_preserve_the_previous_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            shutil.copy(REPO / 'generate-config.py', repo)
            host = repo / 'modules/hosts/vm'
            host.mkdir(parents=True)
            fragment = host / 'config.json'
            (repo / 'host').write_text('vm\n')
            (repo / 'first').write_text('first\n')
            (repo / 'second').write_text('second\n')
            fragment.write_text('{"hostname":"vm"}')
            command = ['python3', str(repo / 'generate-config.py')]
            subprocess.run(command, check=True, capture_output=True)
            previous = (repo / 'user-configuration.json').read_bytes()

            def asset(source, target):
                return {'source': source, 'target': target, 'mode': '0644'}

            for entries, error in (
                (
                    [asset('first', '/etc/example'), asset('second', '/etc/example')],
                    'Multiple modules provide',
                ),
                (
                    [
                        asset('first', 'home/.config/example'),
                        asset('second', 'home/.config/example/child'),
                    ],
                    'overlaps',
                ),
                ([asset('first', '/etc/../example')], 'Invalid asset path'),
                ([asset('first', 'relative/example')], 'Invalid asset path'),
                ([asset('first', '/etc/with\ttab')], 'Invalid asset path'),
                ([asset('missing', '/etc/example')], 'Asset source must be a file'),
                ([asset('/etc/passwd', '/etc/example')], 'Asset source must be a file'),
            ):
                with self.subTest(entries=entries):
                    fragment.write_text(
                        json.dumps({'hostname': 'vm', 'extra': {'files': entries}})
                    )
                    result = subprocess.run(command, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(error, result.stderr)
                    self.assertEqual(
                        (repo / 'user-configuration.json').read_bytes(), previous
                    )


if __name__ == '__main__':
    unittest.main()
