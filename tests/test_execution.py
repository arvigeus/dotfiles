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


class ExecutionTests(unittest.TestCase):
    def test_cargo_packages_install_as_the_user_outside_the_staging_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); commands = root / 'bin'; commands.mkdir()
            home = root / 'real home'; home.mkdir()
            log = root / 'calls.jsonl'
            config = root / 'config.json'
            config.write_text(json.dumps({'extra': {'aur_packages': [],
                'cargo_packages': ['tokei', 'just'], 'flatpak': {'remotes': {}, 'packages': []}}}))
            (commands / 'getent').write_text('#!/bin/sh\nprintf \'%s\\n\' "$ACCOUNT_RECORD"\n')
            (commands / 'runuser').write_text('#!/usr/bin/python3\nimport json,os,sys\nwith open(os.environ["CALL_LOG"],"a") as out: out.write(json.dumps(sys.argv[1:])+"\\n")\n')
            for command in commands.iterdir(): command.chmod(0o755)
            result = subprocess.run(['bash', str(REPO / 'scripts/extra-packages.sh'), str(config), 'tester'],
                env=dict(os.environ, PATH=str(commands)+':'+os.environ['PATH'],
                    HOME=str(root / 'staging'), CARGO_HOME=str(root / 'staging/cargo'),
                    ACCOUNT_RECORD=f'tester:x:1000:1000::{home}:/bin/bash', CALL_LOG=str(log)),
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(calls), 2)
            for call, crate in zip(calls, ['tokei', 'just']):
                self.assertEqual(call[:3], ['-u', 'tester', '--'])
                self.assertIn('HOME='+str(home), call)
                self.assertIn('CARGO_HOME='+str(home / '.local/share/cargo'), call)
                self.assertEqual(call[-5:], ['cargo', 'install', '--locked', '--', crate])
                self.assertFalse(any('staging' in value for value in call))

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

    def test_configure_runs_hooks_from_checkout_and_is_repeatable(self):
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
            (module / 'config.json').write_text(json.dumps({'packages': ['git'], 'extra': {'symlinks': [
                {'source': 'modules/linked/symlinks/home/.config/linked.conf', 'target': str(system_link)}
            ]}}))
            hook = module / 'scripts/50_example.sh'
            hook.parent.mkdir()
            hook.write_text(
                'repo_dir=${DOTFILES_REPO:?}\n'
                'source "$repo_dir/scripts/config-helpers.sh"\n'
                'printf "%s\\n" "$1" | file_write "$HOME/.config/generated.conf"\n')
            subprocess.run(['python3', str(repo / 'generate-config.py')], check=True, capture_output=True)
            config = json.loads((repo / 'user-configuration.json').read_text())
            self.assertEqual(config['extra']['scripts'], ['modules/example/scripts/50_example.sh'])
            self.assertEqual(len(config['custom_commands']), 1)
            # The test runs the real executor unprivileged, without touching /run.
            configure = repo / 'scripts/configure.sh'
            configure.write_text(configure.read_text().replace(
                "[[ $EUID == 0 ]] || { echo 'Run through ./apply.sh or archinstall.' >&2; exit 1; }", ':')
                .replace('/run/system-configuration.json', str(root / 'configuration.json')))
            commands = root / 'bin'
            commands.mkdir()
            record = f'tester:x:{os.getuid()}:{os.getgid()}::{home}:/bin/bash'
            (commands / 'getent').write_text(f'#!/bin/sh\nprintf \'%s\\n\' \'{record}\'\n')
            (commands / 'chown').write_text('#!/bin/sh\nexit 0\n')
            for command in commands.iterdir():
                command.chmod(0o755)
            env = dict(os.environ, PATH=str(commands) + ':' + os.environ['PATH'],
                       SUDO_USER='tester', CONFIG_MODE='live')
            def execute():
                (root / 'configuration.json').unlink(missing_ok=True)
                (root / 'configuration.json').symlink_to(repo / 'user-configuration.json')
                command = config['custom_commands'][0].replace('/run/system-configuration.json', str(root / 'configuration.json'))
                result = subprocess.run(['bash', '-c', command], env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            for _ in range(2):
                execute()
                self.assertEqual((home / '.config/generated.conf').read_text(), 'tester\n')
                self.assertFalse((home / '.config/plain.conf').is_symlink())
                self.assertEqual((home / '.config/plain.conf').read_text(), 'plain\n')
                self.assertEqual((home / '.config/linked.conf').resolve(), links / 'linked.conf')
                self.assertEqual(system_link.resolve(), links / 'linked.conf')
                (home / '.config/plain.conf').write_text('user changes\n')
                self.assertEqual((assets / 'plain.conf').read_text(), 'plain\n')
            # Hook edits apply without regenerating the configuration.
            hook.write_text(hook.read_text().replace('"$1"', '"edited $1"'))
            execute()
            self.assertEqual((home / '.config/generated.conf').read_text(), 'edited tester\n')
            # Installation continues from the user's own checkout before linking assets.
            env['CONFIG_MODE'] = 'install'
            execute()
            checkout = home / 'Projects/dotfiles'
            self.assertEqual((checkout / 'host').read_text(), 'vm\n')
            self.assertEqual((home / '.config/linked.conf').resolve(),
                             checkout / 'modules/linked/symlinks/home/.config/linked.conf')
            self.assertEqual(system_link.resolve(),
                             checkout / 'modules/linked/symlinks/home/.config/linked.conf')

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
            (source / '__pycache__').mkdir()
            (source / 'modules').mkdir()
            (source / 'modules/asset').write_text('asset')
            target = root / 'target'
            target.mkdir()
            with patch.object(plugin, '__file__', str(source / 'scripts/copy-checkout.py')):
                plugin.Plugin().on_install(SimpleNamespace(target=target))
            staged = target / 'root/system-configuration'
            self.assertTrue((staged / 'modules/asset').is_file())
            self.assertFalse((staged / '__pycache__').exists())
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
