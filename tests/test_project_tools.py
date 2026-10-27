"""Project maintenance acts only on explicitly selected temporary repositories."""

import importlib.machinery
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PATH = (
    Path(__file__).resolve().parents[1]
    / 'modules/dev/tools/projects/files/usr/local/bin/project-tools'
)
SPEC = importlib.util.spec_from_loader(
    'project_tools', importlib.machinery.SourceFileLoader('project_tools', str(PATH))
)
project = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(project)


class ProjectMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "User's project"
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'commit.gpgSign', 'false')
        self.git('config', 'core.hooksPath', '/dev/null')
        (self.root / '.gitignore').write_text(
            'build/\n.env\n.env.*\nmise.local.toml\n.direnv/\n'
        )
        (self.root / 'tracked.txt').write_text('committed')
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')

    def git(self, *arguments):
        return subprocess.check_output(
            ['git', '-C', str(self.root), *arguments], text=True
        ).strip()

    def prepare_files(self):
        (self.root / 'build').mkdir()
        (self.root / 'build/output.txt').write_text('build output')
        (self.root / 'build/.env').write_text('nested secret')
        (self.root / '.env').write_text('secret')
        (self.root / 'mise.local.toml').write_text('local')
        (self.root / 'notes.txt').write_text('untracked source notes')
        (self.root / 'tracked.txt').write_text('edited')

    def test_ignored_cleanup_preserves_tracked_untracked_and_local_settings(self):
        self.prepare_files()
        self.assertEqual(project.cleanup_candidates(self.root), ['build/output.txt'])
        project.clean_selected(self.root, ['build/output.txt'])
        self.assertFalse((self.root / 'build/output.txt').exists())
        for path in ['.env', 'build/.env', 'mise.local.toml', 'notes.txt']:
            self.assertTrue((self.root / path).exists(), path)
        self.assertEqual((self.root / 'tracked.txt').read_text(), 'edited')

    def test_changed_selection_is_rejected_before_any_cleanup(self):
        self.prepare_files()
        with self.assertRaises(ValueError):
            project.clean_selected(self.root, ['build', '../outside'])
        self.assertTrue((self.root / 'build/output.txt').exists())

    def test_reset_preserves_environment_nested_repositories_and_reflogs(self):
        self.prepare_files()
        original = self.git('rev-parse', 'HEAD')
        (self.root / 'tracked.txt').write_text('local commit')
        self.git('add', 'tracked.txt')
        self.git('commit', '-qm', 'local commit')
        local = self.git('rev-parse', 'HEAD')
        nested = self.root / 'other-project'
        nested.mkdir()
        subprocess.run(['git', '-C', str(nested), 'init', '-q'], check=True)
        (nested / 'work.txt').write_text('nested work')
        project.reset_to_upstream(self.root, original)
        self.assertEqual((self.root / 'tracked.txt').read_text(), 'committed')
        self.assertFalse((self.root / 'notes.txt').exists())
        self.assertFalse((self.root / 'build/output.txt').exists())
        self.assertTrue((nested / 'work.txt').exists())
        for path in ['.env', 'build/.env', 'mise.local.toml']:
            self.assertTrue((self.root / path).exists(), path)
        self.assertIn(local, self.git('reflog', '--format=%H'))

    def test_active_merge_is_not_aborted_or_reset(self):
        (self.root / '.git/MERGE_HEAD').write_text(self.git('rev-parse', 'HEAD'))
        with self.assertRaisesRegex(ValueError, 'Finish'):
            project.reset_to_upstream(self.root, 'HEAD')
        self.assertTrue((self.root / '.git/MERGE_HEAD').exists())

    def configure_upstream(self):
        remote = Path(self.tmp.name) / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', '-qu', 'origin', 'HEAD')
        return remote

    def test_confirmed_reset_fetches_and_uses_remote_commit(self):
        self.configure_upstream()
        original = self.git('rev-parse', 'HEAD')
        (self.root / 'tracked.txt').write_text('upstream update')
        self.git('commit', '-qam', 'upstream update')
        expected = self.git('rev-parse', 'HEAD')
        self.git('push', '-q', 'origin', 'HEAD')
        self.git('reset', '--hard', original)
        self.prepare_files()
        with patch('builtins.input', return_value=self.root.name):
            self.assertEqual(project.perform('reset', self.root), 0)
        self.assertEqual(self.git('rev-parse', 'HEAD'), expected)
        self.assertEqual((self.root / 'tracked.txt').read_text(), 'upstream update')
        self.assertTrue((self.root / '.env').exists())

    def test_failed_fetch_never_changes_working_files(self):
        self.configure_upstream()
        self.git(
            'remote', 'set-url', 'origin', str(Path(self.tmp.name) / 'missing.git')
        )
        self.prepare_files()
        before = self.git('status', '--porcelain')
        with (
            patch('builtins.input') as prompt,
            self.assertRaises(subprocess.CalledProcessError),
        ):
            project.perform('reset', self.root)
        prompt.assert_not_called()
        self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertEqual((self.root / 'tracked.txt').read_text(), 'edited')

    def test_selected_task_is_revalidated_and_passed_as_one_argument(self):
        with (
            patch.object(project, 'repository', return_value=self.root),
            patch.object(project, 'tasks', return_value=['check:server']),
            patch.object(
                project.subprocess, 'run', return_value=Mock(returncode=0)
            ) as run,
        ):
            self.assertEqual(project.perform('task', self.root, 'check:server'), 0)
            run.assert_called_once_with(
                ['mise', 'run', 'check:server'], cwd=self.root, check=False
            )
            with self.assertRaisesRegex(ValueError, 'no longer available'):
                project.perform('task', self.root, 'removed-task')
            self.assertEqual(run.call_count, 1)

    def test_terminal_launcher_does_not_interpolate_task_or_path(self):
        with patch.object(project.subprocess, 'Popen') as popen:
            project.open_terminal('task', self.root, 'check:server')
        command = popen.call_args.args[0]
        self.assertIn('--dir=' + str(self.root), command)
        self.assertEqual(command[-3:], ['--task', 'check:server', str(self.root)])

    def test_native_git_sync_fetches_pushes_and_only_fast_forwards(self):
        import project_inspector as inspector

        remote = self.configure_upstream()
        (self.root / 'tracked.txt').write_text('local update')
        self.git('commit', '-qam', 'local update')
        self.assertEqual(inspector.sync_action(inspector.git_status(self.root)), 'push')
        self.assertEqual(project.git_action('push', self.root), 0)
        other = Path(self.tmp.name) / 'other'
        subprocess.run(['git', 'clone', '-q', str(remote), str(other)], check=True)

        def other_git(*args):
            return subprocess.check_output(
                ['git', '-C', str(other), *args], text=True
            ).strip()

        for key, value in [
            ('user.name', 'Test'),
            ('user.email', 'test@example.invalid'),
            ('commit.gpgSign', 'false'),
            ('core.hooksPath', '/dev/null'),
        ]:
            other_git('config', key, value)
        (other / 'remote.txt').write_text('upstream update')
        other_git('add', '.')
        other_git('commit', '-qm', 'remote update')
        other_git('push', '-q')
        self.assertEqual(project.git_action('fetch', self.root), 0)
        self.assertEqual(inspector.sync_action(inspector.git_status(self.root)), 'pull')
        self.assertEqual(project.git_action('pull', self.root), 0)
        self.assertTrue((self.root / 'remote.txt').exists())
        # A local and a remote commit produce divergence, never an automatic merge.
        (self.root / 'local.txt').write_text('local')
        self.git('add', '.')
        self.git('commit', '-qm', 'local change')
        (other / 'remote.txt').write_text('another upstream update')
        other_git('commit', '-qam', 'another remote update')
        other_git('push', '-q')
        project.git_action('fetch', self.root)
        self.assertEqual(
            inspector.sync_action(inspector.git_status(self.root)), 'fetch'
        )
        before = self.git('rev-parse', 'HEAD')
        for action in ['push', 'pull']:
            with self.assertRaises(ValueError):
                project.git_action(action, self.root)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)

    def test_commit_uses_native_signing_and_keeps_staged_changes_on_signer_failure(
        self,
    ):
        with self.assertRaisesRegex(ValueError, 'Stage'):
            project.git_action('commit', self.root)
        (self.root / 'tracked.txt').write_text('staged change')
        self.git('add', 'tracked.txt')
        editor = Path(self.tmp.name) / 'editor'
        editor.write_text('#!/bin/sh\nprintf "Test commit\\n" > "$1"\n')
        editor.chmod(0o755)
        signer = Path(self.tmp.name) / 'signer'
        marker = Path(self.tmp.name) / 'signer-called'
        signer.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexit 1\n')
        signer.chmod(0o755)
        self.git('config', 'core.editor', str(editor))
        self.git('config', 'commit.gpgSign', 'true')
        self.git('config', 'gpg.format', 'openpgp')
        self.git('config', 'gpg.program', str(signer))
        self.git('config', 'user.signingKey', 'test-key')
        before = self.git('rev-parse', 'HEAD')
        self.assertNotEqual(project.git_action('commit', self.root), 0)
        self.assertTrue(marker.exists())
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertTrue(self.git('diff', '--cached', '--name-only'))
