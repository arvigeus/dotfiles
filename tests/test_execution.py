import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


class GeneratedExecutionTests(unittest.TestCase):
    def test_xdg_folders_are_published_without_staging_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / 'staging home'
            home = root / 'installed home'
            config = staging / '.config'
            config.mkdir(parents=True)
            module = REPO / 'modules/base/xdg'
            shutil.copyfile(module / 'files/home/.config/user-dirs.dirs', config / 'user-dirs.dirs')
            env = dict(os.environ, HOME=str(staging), XDG_CONFIG_HOME=str(config))
            for _ in range(2):
                subprocess.run(['bash', str(module / 'scripts/45_user-directories.sh')], env=env, check=True)
            subprocess.run(['python3', str(REPO / 'scripts/publish-home.py'), str(staging),
                            str(home), str(os.getuid()), str(os.getgid())], check=True)
            for name in ('Desktop', 'Downloads', 'Documents', 'Music', 'Pictures',
                         'Videos', 'Templates', 'Public', 'Projects'):
                self.assertTrue((home / name).is_dir(), name)
                self.assertEqual((home / name).stat().st_uid, os.getuid())
            user_dirs = (home / '.config/user-dirs.dirs').read_text()
            self.assertIn('XDG_DOWNLOAD_DIR="$HOME/Downloads"', user_dirs)
            self.assertNotIn(str(staging), user_dirs)

    def test_executor_uses_snapshot_and_is_repeatable_without_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'home'
            home.mkdir()
            repo = root / 'repo'
            repo.mkdir()
            shutil.copytree(REPO / 'scripts', repo / 'scripts')
            shutil.copy(REPO / 'generate-config.py', repo)
            (repo / 'host').write_text('vm\n')
            host = repo / 'modules/hosts/vm'
            host.mkdir(parents=True)
            (host / 'config.json').write_text('{"hostname": "vm"}')
            module = repo / 'modules/example'
            assets = module / 'files/home/.config'
            assets.mkdir(parents=True)
            (assets / 'plain.conf').write_text('plain\n')
            links = repo / 'modules/linked/symlinks/home/.config'
            links.mkdir(parents=True)
            (links / 'linked.conf').write_text('linked\n')
            system_link = root / 'system/linked.conf'
            (module / 'links.config.json').write_text(json.dumps({'extra': {'symlinks': [
                {'source': 'modules/linked/symlinks/home/.config/linked.conf', 'target': str(system_link)}
            ]}}))
            (module / 'config.json').write_text('{"packages": ["git"]}')
            (module / 'scripts').mkdir()
            (module / 'scripts/50_example.sh').write_text(
                'repo_dir=${DOTFILES_REPO:?}\n'
                'source "$repo_dir/scripts/config-helpers.sh"\n'
                'file_write "$HOME/.config/generated.conf" <<\'EOF\'\ngenerated\nEOF\n')
            subprocess.run(['python3', str(repo / 'generate-config.py')], check=True, capture_output=True)
            # Remove every executable module input after generation.
            (module / 'scripts/50_example.sh').unlink()
            (repo / 'scripts/config-helpers.sh').unlink()
            executor = repo / 'user-configuration.sh'
            # The test executes only staged home operations as the test user.
            executor.write_text(executor.read_text().replace(
                "[[ $EUID == 0 ]] || { echo 'Run through ./apply.sh or archinstall.' >&2; exit 1; }", ':').replace('/run/system-configuration-context', str(root / 'context')).replace('/run/system-configuration.json', str(root / 'configuration.json')).replace('/var/tmp/system-configuration.', str(root / 'persistent-staging.')))
            commands = root / 'bin'
            commands.mkdir()
            record = f'tester:x:{os.getuid()}:{os.getgid()}::{home}:/bin/bash'
            (commands / 'getent').write_text(f'#!/bin/sh\nprintf \'%s\\n\' \'{record}\'\n')
            (commands / 'systemctl').write_text('#!/bin/sh\nexit 0\n')
            (commands / 'chown').write_text('#!/bin/sh\nexit 0\n')
            for command in commands.iterdir():
                command.chmod(0o755)
            env = dict(os.environ, PATH=str(commands) + ':' + os.environ['PATH'],
                       SUDO_USER='tester', CONFIG_MODE='live')
            temporary_mount = root / 'temporary-mount'
            temporary_mount.mkdir()
            env['TMPDIR'] = str(temporary_mount)
            config = json.loads((repo / 'user-configuration.json').read_text())
            def execute():
                (root / 'configuration.json').unlink(missing_ok=True)
                (root / 'configuration.json').symlink_to(repo / 'user-configuration.json')
                for command in config['custom_commands']:
                    command = command.replace('/run/system-configuration.json', str(root / 'configuration.json'))
                    result = subprocess.run(['bash', '-c', command], env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    # arch-chroot -S discards /tmp after each custom command.
                    # Preserve no temporary files there between invocations.
                    shutil.rmtree(temporary_mount)
                    temporary_mount.mkdir()
            for _ in range(2):
                execute()
                self.assertFalse((root / 'context').exists())
                self.assertEqual((home / '.config/generated.conf').read_text(), 'generated\n')
                self.assertFalse((home / '.config/plain.conf').is_symlink())
                self.assertEqual((home / '.config/plain.conf').read_text(), 'plain\n')
                self.assertEqual((home / '.config/linked.conf').resolve(), links / 'linked.conf')
                self.assertEqual(system_link.resolve(), links / 'linked.conf')
                (home / '.config/plain.conf').write_text('user changes\n')
                self.assertEqual((assets / 'plain.conf').read_text(), 'plain\n')
            self.assertFalse((home / '.local/state/system-config').exists())
            # Installation publishes the same generated configuration into the
            # user's checkout before resolving home links and executing hooks.
            env['CONFIG_MODE'] = 'install'
            execute()
            checkout = home / 'Projects/dotfiles'
            self.assertFalse((home / '.config/plain.conf').is_symlink())
            self.assertEqual((home / '.config/plain.conf').read_text(), 'plain\n')
            self.assertEqual((home / '.config/linked.conf').resolve(),
                             checkout / 'modules/linked/symlinks/home/.config/linked.conf')
            self.assertEqual(system_link.resolve(),
                             checkout / 'modules/linked/symlinks/home/.config/linked.conf')
            self.assertEqual((home / '.config/generated.conf').read_text(), 'generated\n')

    def test_validation_invokes_only_archinstall_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'args'
            for name, body in (
                ('sudo', 'exec "$@"'),
                ('archinstall', 'printf "%s\\n" "$@" > "$ARG_LOG"'),
            ):
                command = root / name
                command.write_text('#!/bin/sh\n' + body + '\n')
                command.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], ARG_LOG=str(log))
            subprocess.run(['bash', str(REPO / 'validate.sh')], env=env, check=True)
            args = log.read_text().splitlines()
            self.assertIn('--dry-run', args)
            self.assertIn('--silent', args)
            self.assertIn('--offline', args)
            self.assertNotIn('--plugin', args)

    def test_bootstrap_plugin_stages_assets_without_scratchpad(self):
        spec = importlib.util.spec_from_file_location('copy_checkout', REPO / 'scripts/copy-checkout.py')
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'repo'
            (source / 'scripts').mkdir(parents=True)
            (source / 'user-configuration.json').write_text('{}')
            (source / 'live-migrate.sh').write_text('do not copy')
            (source / 'modules').mkdir()
            (source / 'modules/asset').write_text('asset')
            target = root / 'target'
            target.mkdir()
            with patch.object(plugin, '__file__', str(source / 'scripts/copy-checkout.py')):
                plugin.Plugin().on_install(SimpleNamespace(target=target))
            staged = target / 'root/system-configuration'
            self.assertTrue((staged / 'modules/asset').is_file())
            self.assertFalse((staged / 'live-migrate.sh').exists())
            self.assertEqual(os.readlink(target / 'run/system-configuration.json'),
                             '/root/system-configuration/user-configuration.json')


class LiveParserTests(unittest.TestCase):
    def test_installation_only_configuration_is_never_passed_to_live_parser(self):
        spec = importlib.util.spec_from_file_location('apply_config', REPO / 'scripts/apply-config.py')
        executor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(executor)
        captured = {}

        class ArchConfig:
            @classmethod
            def from_config(cls, raw, args):
                captured.update(raw)
                return raw

        module = ModuleType('archinstall.lib.args')
        module.ArchConfig = ArchConfig
        module.Arguments = SimpleNamespace
        with patch.dict(sys.modules, {'archinstall.lib.args': module}):
            executor.native_config({
                'hostname': 'vm', 'packages': ['git'], 'disk_config': {'wipe': True},
                'bootloader_config': {}, 'auth_config': {}, 'extra': {}, 'custom_commands': [],
            })
        self.assertEqual(captured, {'hostname': 'vm', 'packages': ['git']})
        self.assertFalse(hasattr(executor.LiveInstaller, 'minimal_installation'))
        self.assertFalse(hasattr(executor.LiveInstaller, 'mount_ordered_layout'))


if __name__ == '__main__':
    unittest.main()
