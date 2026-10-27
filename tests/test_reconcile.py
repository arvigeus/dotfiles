"""Reconciliation preserves edits and checkpoints only completed changes."""
import importlib.util
import io
import json
import os
import pwd
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
import reconcile
import reconcile_packages
import reconcile_services


class Answers:
    def __init__(self, *answers):
        self.answers = iter(answers)
        self.messages = []

    def choose(self, message, choices, default):
        self.messages.append(message)
        return next(self.answers, default)


class FileReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.write_text('repository\n')
        self.target = self.root / 'live/config'
        self.state_dir = self.root / 'state'
        self.entries = [(self.source, self.target, os.getuid(), os.getgid())]

    def sync(self, answers=(), entries=None, dry_run=False):
        state = reconcile.State(self.state_dir, dry_run=dry_run)
        review = Answers(*answers)
        files = reconcile.Files(state, review)
        result = files.sync('test', self.entries if entries is None else entries)
        return result, files, review

    def test_identical_files_keep_mtime_and_clean_updates_ignore_checkout_time(self):
        self.sync()
        timestamp = self.target.stat().st_mtime_ns
        self.sync()
        self.assertEqual(self.target.stat().st_mtime_ns, timestamp)
        self.source.write_text('new repository\n')
        os.utime(self.source, ns=(1, 1))
        self.assertTrue(self.sync()[0])
        self.assertEqual(self.target.read_text(), 'new repository\n')
        backups = list((self.state_dir / 'backups').rglob('config'))
        self.assertEqual([path.read_text() for path in backups], ['repository\n'])

    def test_local_and_simultaneous_edits_require_explicit_review(self):
        self.sync()
        self.target.write_text('local\n')
        complete, _, review = self.sync()
        self.assertFalse(complete)
        self.assertEqual(len(review.messages), 1)
        self.assertEqual(self.target.read_text(), 'local\n')
        self.source.write_text('both changed\n')
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertTrue(self.sync(('d', 'r'))[0])
        self.assertIn('-local', output.getvalue())
        self.assertEqual(self.target.read_text(), 'both changed\n')
        self.assertTrue(any(path.read_text() == 'local\n' for path in (self.state_dir / 'backups').rglob('config')))

    def test_first_adoption_preserves_an_unknown_existing_file(self):
        self.target.parent.mkdir()
        self.target.write_text('unknown\n')
        self.assertFalse(self.sync()[0])
        self.assertEqual(self.target.read_text(), 'unknown\n')
        self.assertFalse(self.state_dir.exists())
        self.assertTrue(self.sync(('r',))[0])

    def test_removed_files_are_deleted_only_when_clean_or_approved(self):
        self.sync()
        self.target.write_text('local\n')
        self.assertFalse(self.sync(entries=[])[0])
        self.assertIn(str(self.target), reconcile.State(self.state_dir).data['files']['test'])
        self.assertTrue(self.sync(('r',), entries=[])[0])
        self.assertFalse(self.target.exists())
        self.assertEqual(reconcile.State(self.state_dir).data['files']['test'], {})

    def test_clean_removed_file_is_backed_up_and_deleted(self):
        self.sync()
        self.assertTrue(self.sync(entries=[])[0])
        self.assertFalse(self.target.exists())
        self.assertTrue(list((self.state_dir / 'backups').rglob('config')))

    def test_symlink_replacement_never_writes_through_it(self):
        outside = self.root / 'outside'
        outside.write_text('untouched\n')
        self.target.parent.mkdir()
        self.target.symlink_to(outside)
        self.assertTrue(self.sync(('r',))[0])
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(outside.read_text(), 'untouched\n')

    def test_tracked_dangling_links_can_be_removed(self):
        self.source.unlink()
        self.source.symlink_to(self.root / 'missing')
        self.sync()
        self.assertTrue(self.target.is_symlink())
        self.assertTrue(self.sync(entries=[])[0])
        self.assertFalse(self.target.is_symlink())

    def test_missing_source_or_linked_parent_fails_before_any_file_is_published(self):
        missing = (self.root / 'missing', self.root / 'later', os.getuid(), os.getgid())
        with self.assertRaisesRegex(ValueError, 'Missing source'):
            self.sync(entries=[*self.entries, missing])
        self.assertFalse(self.target.exists())
        outside = self.root / 'outside'
        outside.mkdir()
        self.target.parent.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'directory symlink'):
            self.sync()
        self.assertEqual(list(outside.iterdir()), [])

    def test_local_change_during_backup_is_not_overwritten(self):
        self.sync()
        self.source.write_text('updated\n')
        original = reconcile.shutil.copy2
        def changed(source, destination, **kwargs):
            result = original(source, destination, **kwargs)
            if source == self.target:
                self.target.write_text('concurrent edit\n')
            return result
        with patch.object(reconcile.shutil, 'copy2', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed while being backed up'):
                self.sync()
        self.assertEqual(self.target.read_text(), 'concurrent edit\n')

    def test_interrupted_state_checkpoint_is_recovered_from_matching_content(self):
        self.sync()
        self.source.write_text('updated\n')
        with patch.object(reconcile.State, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.sync()
        self.assertEqual(self.target.read_text(), 'updated\n')
        self.assertTrue(self.sync()[0])
        self.assertEqual(reconcile.State(self.state_dir).data['files']['test'][str(self.target)], reconcile.fingerprint(self.target))

    def test_dry_run_and_corrupt_state_never_write_targets(self):
        self.assertTrue(self.sync(dry_run=True)[0])
        self.assertFalse(self.target.exists())
        self.assertFalse(self.state_dir.exists())
        self.state_dir.mkdir()
        (self.state_dir / 'state.json').write_text('{broken')
        with self.assertRaises(ValueError):
            self.sync()
        self.assertFalse(self.target.exists())

    def test_two_scopes_cannot_silently_manage_the_same_destination(self):
        self.sync()
        state = reconcile.State(self.state_dir)
        with self.assertRaisesRegex(ValueError, 'Multiple owners'):
            reconcile.Files(state).sync('another-owner', self.entries)


class PackageReconciliationTests(unittest.TestCase):
    def package(self, name, depends=(), provides=(), reason=0, required=(), optional=()):
        return SimpleNamespace(name=name, version='1', desc=name, isize=1024, depends=depends,
                               provides=provides, reason=reason, compute_requiredby=lambda: required,
                               compute_optionalfor=lambda: optional)

    def test_providers_and_transitive_dependencies_are_protected(self):
        packages = [self.package('app', ['virtual>=2']), self.package('provider', ['lib'], ['virtual=2']),
                    self.package('lib'), self.package('extra'), self.package('orphan', reason=1),
                    self.package('other-dependency', reason=1, required=['extra'])]
        handle = SimpleNamespace(get_localdb=lambda: SimpleNamespace(pkgcache=packages))
        def satisfy(packages, dependency):
            return next((p for p in packages if p.name == dependency or
                         (dependency == 'virtual>=2' and 'virtual=2' in p.provides)), None)
        with patch('pyalpm.find_satisfier', side_effect=satisfy):
            missing, candidates = reconcile_packages.Inventory(handle).status(['repo/app'], ['absent-aur'])
        self.assertEqual(missing, ['absent-aur (AUR)'])
        self.assertEqual([p.name for p in candidates], ['extra', 'orphan'])

    def test_review_never_cascades_and_rechecks_candidates_after_each_choice(self):
        a, b = self.package('a'), self.package('b')
        snapshots = iter([([], [a, b]), ([], [a, b]), ([], [])])
        inventory = lambda: SimpleNamespace(status=lambda *_: next(snapshots))
        calls = []
        def run(argv, check):
            calls.append(argv)
            return SimpleNamespace(returncode=1)
        review = Answers('r')
        reconcile_packages.review_removals(['wanted'], [], review, inventory, run)
        self.assertEqual(calls, [['pacman', '-R', '--noconfirm', '--', 'a']])
        self.assertEqual(len(review.messages), 1)

    def test_missing_declarations_block_every_removal(self):
        inventory = lambda: SimpleNamespace(status=lambda *_: (['missing'], [self.package('extra')]))
        with self.assertRaisesRegex(ValueError, 'refusing removals'):
            reconcile_packages.review_removals([], [], Answers('r'), inventory, lambda *_: self.fail('removal attempted'))


class ServiceReconciliationTests(unittest.TestCase):
    def test_only_previously_managed_user_units_are_disabled_or_unmasked(self):
        with tempfile.TemporaryDirectory() as directory:
            state = reconcile.State(Path(directory))
            state.data.update(user_services=['old.service'], masked_user_services=['old-mask.service'])
            state.save()
            calls = []
            reconcile_services.apply_user({'user_services': ['new.service'], 'masked_user_services': ['new-mask.service']}, state,
                                          lambda *args: calls.append(args))
            self.assertIn(('systemctl', '--global', 'disable', 'old.service'), calls)
            self.assertIn(('systemctl', '--global', 'unmask', 'old-mask.service'), calls)
            self.assertEqual(state.data['user_services'], ['new.service'])
            self.assertFalse(any('stop' in call or 'restart' in call for call in calls))


class ApplyPlanningTests(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location('reconcile_apply', REPO / 'scripts/apply-config.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_concurrent_apply_is_refused_and_lock_is_reusable_after_exit(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            with module.acquire_lock(path):
                with self.assertRaisesRegex(ValueError, 'already running'):
                    module.acquire_lock(path)
            with module.acquire_lock(path):
                pass

    def test_native_planning_collects_packages_and_never_executes_commands(self):
        module = self.load()
        raw = json.loads((REPO / 'user-configuration.json').read_text())
        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'run', side_effect=AssertionError('command executed')):
            plan = module.native_plan(module.native_config(raw), Path(directory))
            self.assertIn('zram-generator', plan.packages)
            self.assertIn('pipewire', plan.packages)
            self.assertIn('bluetooth.service', plan.services)
            self.assertIn('iwd.service', plan.disabled_services)
            self.assertTrue((Path(directory) / 'etc/systemd/zram-generator.conf').is_file())
            self.assertTrue((Path(directory) / 'etc/localtime').is_symlink())

    def test_apply_wrapper_dry_run_bypasses_validation_and_forwards_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'apply.sh').write_text((REPO / 'apply.sh').read_text())
            (root / 'validate.sh').write_text('#!/bin/sh\nexit 97\n')
            (root / 'validate.sh').chmod(0o755)
            commands = root / 'bin'
            commands.mkdir()
            (commands / 'sudo').write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            (commands / 'sudo').chmod(0o755)
            result = subprocess.run(['bash', str(root / 'apply.sh'), '--dry-run', '--no-package-review'],
                                    env=dict(os.environ, PATH=str(commands) + ':' + os.environ['PATH']),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--dry-run\n--no-package-review', result.stdout)

    def test_full_apply_freezes_configuration_and_preserves_subprocess_checkpoints(self):
        self.workflow()

    def test_failed_early_hook_prevents_package_transactions_and_restores_runtime_link(self):
        self.workflow(fail_pre=True)

    def workflow(self, fail_pre=False):
        module = self.load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / 'repo'
            repo.mkdir()
            (repo / 'generate-config.py').write_text((REPO / 'generate-config.py').read_text())
            config = repo / 'user-configuration.json'
            raw = {'packages': ['wanted'], 'custom_commands': ['fixture-custom-command'],
                   'extra': {'desktop': 'hyprland', 'files': [], 'symlinks': [], 'checks': [], 'pre': [], 'scripts': []}}
            config.write_text(json.dumps(raw))
            runtime = root / 'runtime-config'
            runtime.symlink_to(config)
            calls = []
            state_root = root / 'state'
            account = pwd.getpwuid(os.getuid())
            def plan(parsed, target):
                target.mkdir(parents=True)
                return SimpleNamespace(target=target, packages=parsed.packages, services=[], disabled_services=[], commands=[])
            def execute(argv, **kwargs):
                calls.append(argv)
                frozen = Path(kwargs['env']['DOTFILES_CONFIG'])
                self.assertEqual(json.loads(frozen.read_text())['packages'], ['wanted'])
                if '--pre' in argv:
                    self.assertEqual(runtime.resolve(), frozen)
                    if fail_pre:
                        raise subprocess.CalledProcessError(9, argv)
                    raw['packages'] = ['edited-during-apply']
                    config.write_text(json.dumps(raw))
                if 'fixture-custom-command' in argv:
                    state = reconcile.State(state_root / str(account.pw_uid))
                    state.data['files']['hook-checkpoint'] = {}
                    state.save()
                return SimpleNamespace(returncode=0)
            with (patch.object(module, 'STATE_ROOT', state_root),
                  patch.object(module, 'APPLY_LOCK', root / 'lock'),
                  patch.object(module, 'RUNTIME_CONFIG', runtime),
                  patch.object(module.os, 'geteuid', return_value=0),
                  patch.dict(os.environ, SUDO_USER=account.pw_name),
                  patch.object(module, 'native_config', side_effect=lambda value: SimpleNamespace(packages=value['packages'])),
                  patch.object(module, 'native_plan', side_effect=plan),
                  patch.object(module, 'repositories', side_effect=lambda *_: calls.append(['repositories'])),
                  patch.object(module, 'run', side_effect=lambda *args: calls.append(list(args))),
                  patch.object(module.subprocess, 'run', side_effect=execute),
                  patch.object(module, 'review_removals', side_effect=lambda *_: calls.append(['review'])),
                  patch.object(sys, 'argv', ['apply-config.py', str(config)])):
                if fail_pre:
                    with self.assertRaises(subprocess.CalledProcessError):
                        module.main()
                else:
                    module.main()
            self.assertEqual(runtime.resolve(), config)
            transactions = [call for call in calls if call[0] == 'pacman']
            if fail_pre:
                self.assertEqual(transactions, [])
            else:
                self.assertEqual(transactions, [['pacman', '-Syu', '--needed', '--', 'wanted']])
                self.assertEqual(calls[-1], ['review'])
                self.assertIn('hook-checkpoint', reconcile.State(state_root / str(account.pw_uid)).data['files'])


if __name__ == '__main__':
    unittest.main()
