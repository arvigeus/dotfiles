import json
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / 'scripts/private_files.py'


class PrivateFilesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'live'
        self.home.mkdir()
        self.private = self.root / 'private'
        self.config = self.root / 'config.json'

    def configure(self, files=(), symlinks=()):
        self.config.write_text(
            json.dumps(
                {
                    'extra': {
                        'private': {'files': list(files), 'symlinks': list(symlinks)}
                    }
                }
            )
        )

    def run_script(self, *command, home=None, check=True):
        result = subprocess.run(
            command,
            env=dict(
                os.environ,
                HOME=str(home or self.home),
                PATH=os.defpath,
                GIT_CONFIG_NOSYSTEM='1',
                GIT_CONFIG_GLOBAL=os.devnull,
            ),
            capture_output=True,
            text=True,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def backup(self, *args, check=True):
        return self.run_script(
            'bash',
            str(REPO / 'backup.sh'),
            '--config',
            str(self.config),
            '--destination',
            str(self.private),
            *args,
            check=check,
        )

    def apply(self, *args, home=None, check=True):
        return self.run_script(
            'bash', str(self.private / 'apply.sh'), *args, home=home, check=check
        )

    def asset(self, path, content='fixture', mode=0o600):
        target = self.home / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        target.chmod(mode)
        return target

    def test_standalone_restore_after_git_clone_recovers_modes_and_keeps_originals(
        self,
    ):
        self.configure(
            ['home/.ssh', 'home/empty'], ['home/.config/token', 'home/empty-link']
        )
        self.asset('.ssh/key', 'example-key')
        self.asset('.ssh/tool', 'example-executable', 0o700)
        (self.home / '.ssh').chmod(0o700)
        (self.home / '.ssh/empty').mkdir(mode=0o700)
        (self.home / 'empty').mkdir(mode=0o700)
        (self.home / 'empty-link').mkdir(mode=0o700)
        external = self.asset('external-token', 'example-token')
        link = self.home / '.config/token'
        link.parent.mkdir()
        link.symlink_to(external)
        self.backup()
        self.assertTrue((self.private / '.git').is_dir())
        self.assertFalse(
            (self.private / 'modules/backup/symlinks/home/.config/token').is_symlink()
        )
        self.run_script('git', '-C', str(self.private), 'add', '.')
        self.run_script(
            'git',
            '-C',
            str(self.private),
            '-c',
            'user.name=Fixture',
            '-c',
            'user.email=fixture@example.invalid',
            'commit',
            '-qm',
            'Fixture',
        )
        clone = self.root / 'clone'
        self.run_script(
            'git', 'clone', '--quiet', '--no-hardlinks', str(self.private), str(clone)
        )
        self.private = clone
        # A missing live directory must retain a Git-omitted empty snapshot too.
        (self.home / 'empty').rmdir()
        self.backup()
        restored = self.root / 'restored'
        (restored / '.ssh').mkdir(parents=True)
        (restored / '.ssh/existing').write_text('keep-me')
        self.apply(home=restored)
        self.assertEqual((restored / '.ssh/key').read_text(), 'example-key')
        self.assertEqual((restored / '.ssh/key').stat().st_mode & 0o777, 0o600)
        self.assertEqual((restored / '.ssh/tool').stat().st_mode & 0o777, 0o700)
        self.assertEqual((restored / '.ssh').stat().st_mode & 0o777, 0o700)
        self.assertTrue((restored / '.ssh/empty').is_dir())
        self.assertTrue((restored / 'empty').is_dir())
        self.assertTrue((restored / 'empty-link').is_dir())
        self.assertTrue((restored / 'empty-link').is_symlink())
        self.assertEqual(
            next(restored.glob('.ssh.before-private-*'))
            .joinpath('existing')
            .read_text(),
            'keep-me',
        )
        token = restored / '.config/token'
        self.assertTrue(token.is_symlink())
        self.assertEqual(token.read_text(), 'example-token')
        self.assertEqual(token.stat().st_mode & 0o777, 0o600)
        self.home = restored
        token.write_text('updated')
        self.backup()
        self.assertEqual(token.read_text(), 'updated')
        # Reapplying an already installed link must not replace it with a saved copy.
        self.apply(home=restored)
        self.assertFalse(list(token.parent.glob('token.before-private-*')))

    def test_refresh_removes_deleted_children_and_missing_source_retains_backup(self):
        self.configure(['home/private'])
        self.asset('private/keep', 'one')
        removed = self.asset('private/removed')
        self.backup()
        removed.unlink()
        self.asset('private/keep', 'two')
        self.backup()
        snapshot = self.private / 'modules/backup/files/home/private'
        self.assertFalse((snapshot / 'removed').exists())
        shutil.rmtree(self.home / 'private')
        result = self.backup()
        self.assertIn('previous backup retained', result.stderr)
        self.assertEqual((snapshot / 'keep').read_text(), 'two')
        restored = self.root / 'restored'
        restored.mkdir()
        self.apply(home=restored)
        self.assertEqual((restored / 'private/keep').read_text(), 'two')

    def test_dry_runs_do_not_create_or_modify_outputs_or_run_hooks(self):
        self.configure(['home/token'])
        self.asset('token')
        self.backup('--dry-run')
        self.assertFalse(self.private.exists())
        self.backup()
        hook = self.private / 'modules/custom/scripts/50_hook.sh'
        hook.parent.mkdir(parents=True)
        hook.write_text('touch "$HOME/hook-ran"\n')
        restored = self.root / 'restored'
        restored.mkdir()
        self.apply('--dry-run', home=restored)
        self.assertEqual(list(restored.iterdir()), [])

    def test_custom_modules_merge_config_install_assets_and_run_ordered_hooks(self):
        self.configure(['home/token'])
        self.asset('token', 'snapshot')
        self.backup()
        for name, number in [('first', 90), ('second', 10)]:
            module = self.private / 'modules' / name
            asset = module / 'files/home' / f'{name}.conf'
            asset.parent.mkdir(parents=True)
            asset.write_text(name)
            (module / 'config.json').write_text(
                json.dumps({'extra': {'custom': [name]}})
            )
            hook = module / 'scripts' / f'{number}_configure.sh'
            hook.parent.mkdir()
            hook.write_text(f"""test -f "$HOME/{name}.conf"
test -f "$HOME/token"
test "$PWD" = "$DOTFILES_REPO"
test "$1" = "$USERNAME"
python3 -c 'import json,os; assert json.load(open(os.environ["DOTFILES_CONFIG"]))["extra"]["custom"] == ["first", "second"]'
echo {name} >> "$HOME/hook-order"
""")
        restored = self.root / 'restored'
        restored.mkdir()
        self.apply(home=restored)
        self.assertEqual((restored / 'hook-order').read_text(), 'second\nfirst\n')
        self.assertEqual((restored / 'first.conf').stat().st_mode & 0o777, 0o600)
        (self.private / 'README.md').write_text('user documentation')
        self.backup()
        self.assertTrue((self.private / 'modules/first/config.json').exists())
        self.assertEqual((self.private / 'README.md').read_text(), 'user documentation')

    def test_invalid_paths_overlaps_and_broken_links_fail(self):
        for paths in [
            ['home/../escape'],
            ['relative/path'],
            ['/'],
            ['//etc/key'],
            ['home/a', 'home/a/b'],
            ['home/a', '/home/a'],
        ]:
            with self.subTest(paths=paths):
                self.configure(paths)
                self.assertNotEqual(self.backup(check=False).returncode, 0)
                self.assertFalse(self.private.exists())
        self.configure(['home/token'])
        (self.home / 'token').symlink_to(self.home / 'absent')
        self.assertIn('Broken source symlink', self.backup(check=False).stderr)

    def test_socket_is_skipped_and_failed_snapshot_preserves_previous_backup(self):
        self.configure(['home/keys'])
        self.asset('keys/key', 'old')
        spec = importlib.util.spec_from_file_location('private_files', RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(
            module.Path, 'stat', return_value=SimpleNamespace(st_mode=stat.S_IFSOCK)
        ):
            module.snapshot(self.home / 'keys/agent', self.root / 'unused')
        self.assertFalse((self.root / 'unused').exists())
        self.backup()
        snapshot = self.private / 'modules/backup/files/home/keys'
        self.assertFalse((snapshot / 'agent').exists())
        self.asset('keys/key', 'new')
        (self.home / 'keys/cycle').symlink_to(
            self.home / 'keys', target_is_directory=True
        )
        result = self.backup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cycle', result.stderr)
        self.assertEqual((snapshot / 'key').read_text(), 'old')

    def test_locks_are_omitted_from_refreshed_snapshot_manifest_and_clone(self):
        self.configure(['home/.gnupg', 'home/.config/app'])
        self.asset('.gnupg/private-keys-v1.d/example.key', 'private-key')
        self.asset('.gnupg/public-keys.d/pubring.db', 'public-keys')
        self.asset('.config/app/settings.json', '{}')
        self.backup()
        payload = self.private / 'modules/backup'
        # A refresh must remove locks captured by an earlier backup engine.
        old_lock = payload / 'files/home/.gnupg/public-keys.d/pubring.db.lock'
        old_lock.write_text('old lock')
        manifest = json.loads((payload / 'config.json').read_text())
        manifest['permissions'][str(old_lock.relative_to(payload))] = 0o600
        (payload / 'config.json').write_text(json.dumps(manifest))
        for name in [
            '.gnupg/public-keys.d/pubring.db.lock',
            '.gnupg/public-keys.d/.#lk0x123.host.456',
            '.config/app/settings.lock',
        ]:
            self.asset(name, 'runtime lock')
        # Skip before stat: a lock may already be gone or link to a missing file.
        (self.home / '.gnupg/.#lk-vanished').symlink_to(self.home / 'absent')
        result = self.backup()
        self.assertIn('Skip lock:', result.stderr)
        manifest = json.loads((payload / 'config.json').read_text())
        self.assertFalse(
            any(
                name.endswith('.lock') or '/.#lk' in name
                for name in manifest['permissions']
            )
        )
        self.assertEqual(
            (payload / 'files/home/.gnupg/public-keys.d/pubring.db').read_text(),
            'public-keys',
        )
        self.assertFalse(old_lock.exists())
        # Ignore rules also protect handwritten modules and newly created locks.
        ignored = [
            'root.lock',
            'modules/custom/files/home/nested.lock',
            'modules/custom/files/home/.#lk0x789.host.123',
        ]
        for name in ignored:
            self.run_script('git', '-C', str(self.private), 'check-ignore', '-q', name)
        self.run_script('git', '-C', str(self.private), 'add', '.')
        self.run_script(
            'git',
            '-C',
            str(self.private),
            '-c',
            'user.name=Fixture',
            '-c',
            'user.email=fixture@example.invalid',
            'commit',
            '-qm',
            'Fixture',
        )
        clone = self.root / 'clone'
        self.run_script(
            'git', 'clone', '--quiet', '--no-hardlinks', str(self.private), str(clone)
        )
        self.private = clone
        restored = self.root / 'restored'
        restored.mkdir()
        self.apply(home=restored)
        self.assertEqual(
            (restored / '.gnupg/private-keys-v1.d/example.key').read_text(),
            'private-key',
        )
        self.assertFalse(list(restored.rglob('*.lock')))
        self.assertFalse(list(restored.rglob('.#lk*')))

    def test_restore_rejects_symlink_parent_and_conflict_before_installing(self):
        self.configure(['home/.ssh/key', 'home/token'])
        self.asset('.ssh/key')
        self.asset('token')
        self.backup()
        restored, outside = self.root / 'restored', self.root / 'outside'
        restored.mkdir()
        outside.mkdir()
        (restored / '.ssh').symlink_to(outside)
        result = self.apply(home=restored, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((restored / 'token').exists())
        self.assertEqual(list(outside.iterdir()), [])
        (restored / '.ssh').unlink()
        collision = self.private / 'modules/collision/files/home/token'
        collision.parent.mkdir(parents=True)
        collision.write_text('collision')
        result = self.apply(home=restored, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Overlapping', result.stderr)
        self.assertEqual(list(restored.iterdir()), [])

    def test_generation_merges_private_declarations_from_selected_modules(self):
        public = self.root / 'public'
        public.mkdir()
        shutil.copy(REPO / 'generate-config.py', public)
        (public / 'host').write_text('vm')
        for name, kind, path in [
            ('hosts/vm', 'files', 'home/a'),
            ('app', 'symlinks', 'home/b'),
        ]:
            module = public / 'modules' / name
            module.mkdir(parents=True)
            (module / 'config.json').write_text(
                json.dumps({'extra': {'private': {kind: [path]}}})
            )
        self.run_script('python3', str(public / 'generate-config.py'))
        generated = json.loads((public / 'user-configuration.json').read_text())
        self.assertEqual(
            generated['extra']['private'], {'files': ['home/a'], 'symlinks': ['home/b']}
        )


if __name__ == '__main__':
    unittest.main()
