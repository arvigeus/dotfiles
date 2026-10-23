"""Project discovery reads declarations and Git metadata, without executing projects."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / 'modules/dev/tools/projects/files/usr/local/lib/project-tools'
sys.path.insert(0, str(LIB))
import project_inspector as inspector


class ProjectOverviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        self.root.mkdir()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def init_git(self):
        self.git('init', '-q', '-b', 'main')
        for key, value in [('user.name', 'Test'), ('user.email', 'test@example.invalid'),
                           ('commit.gpgSign', 'false'), ('core.hooksPath', '/dev/null')]:
            self.git('config', key, value)

    def test_detects_frameworks_workspace_icon_and_declarations_without_execution(self):
        self.write('package.json', json.dumps({'name': 'Example', 'description': 'A project', 'version': '1.2.3',
                                              'devDependencies': {'typescript': '*'}, 'dependencies': {'react': '*', 'next': '*'}}))
        self.write('Cargo.toml', '[workspace]\nmembers=["apps/app"]\n')
        self.write('apps/app/Cargo.toml', '[dependencies]\ndioxus="0.7"\n')
        self.write('pyproject.toml', '[project]\nname="backend"\ndependencies=["fastapi>=0.1"]\n')
        self.write('bun.lock', '{}')
        icon = self.write('favicon.svg', '<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.write('.tool-versions', 'python 3.14\n')
        self.write('mise.toml', '''[tools]
node = "26"
rust = {version="1.98", components=["clippy"]}
[env]
SECRET = "do-not-display"
[tasks.check]
description = "Check everything"
run = "touch MUST_NOT_EXIST"
[tasks.hidden]
hide = true
run = "false"
''')
        task = self.write('mise-tasks/build', '#!/bin/sh\ntouch MUST_NOT_EXIST\n'); task.chmod(0o755)
        with patch.object(inspector, 'language_summary', return_value=({'languages': [], 'partial': False}, [])), \
                patch.object(inspector.subprocess, 'run', wraps=subprocess.run) as commands:
            snapshot = inspector.inspect(self.root)
        self.assertTrue(all(c.args[0][0] == 'git' for c in commands.call_args_list))
        self.assertEqual(snapshot['name'], 'Example')
        self.assertEqual(snapshot['version'], '1.2.3')
        technologies = {t['name'] for t in snapshot['technologies']}
        self.assertTrue({'Rust', 'JavaScript', 'TypeScript', 'React', 'Next.js', 'Dioxus', 'Python', 'FastAPI', 'Mise'} <= technologies)
        self.assertEqual(snapshot['icon'], str(icon))
        self.assertEqual(snapshot['managers'], ['Bun'])
        self.assertEqual([t['name'] for t in snapshot['mise']['tasks']], ['build', 'check'])
        self.assertEqual({t['name']: t['version'] for t in snapshot['mise']['tools']},
                         {'node': '26', 'python': '3.14', 'rust': '1.98'})
        self.assertNotIn('do-not-display', json.dumps(snapshot))
        self.assertFalse((self.root / 'MUST_NOT_EXIST').exists())

    def test_git_status_handles_renames_and_redacts_credentials_without_fetching(self):
        self.init_git()
        self.write('one', 'one'); self.write('two', 'two')
        self.git('add', '.'); self.git('commit', '-qm', 'Initial commit')
        self.git('remote', 'add', 'origin', 'https://user:secret@github.com/example/project.git?token=secret')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.git('config', 'branch.main.remote', 'origin'); self.git('config', 'branch.main.merge', 'refs/heads/main')
        (self.root / 'one').rename(self.root / 'renamed\nfile')
        self.git('add', '-A')
        self.write('two', 'modified'); self.write('notes', 'untracked')
        with patch.object(inspector, 'language_summary', return_value=({'languages': [], 'partial': False}, [])), \
                patch.object(inspector.subprocess, 'run', wraps=subprocess.run) as commands:
            snapshot = inspector.inspect(self.root)
        state = snapshot['git']
        self.assertEqual((state['staged'], state['modified'], state['untracked']), (1, 1, 1))
        self.assertEqual((state['ahead'], state['behind']), (0, 0))
        self.assertEqual(state['upstream'], 'origin/main')
        self.assertEqual(state['remote']['url'], 'https://github.com/example/project')
        self.assertNotIn('secret', json.dumps(snapshot))
        self.assertFalse(any('fetch' in c.args[0] for c in commands.call_args_list))
        for call in commands.call_args_list:
            self.assertIn('--no-optional-locks', call.args[0])
            self.assertIn('core.fsmonitor=false', call.args[0])
        self.git('checkout', '--detach', '-q')
        self.assertTrue(inspector.git_status(self.root)['branch'].startswith('Detached'))

    def test_missing_malformed_oversized_and_external_files_are_handled(self):
        self.write('Cargo.toml', 'not = [valid')
        outside = Path(self.tmp.name) / 'package.json'; outside.write_text('{"name":"external"}')
        (self.root / 'package.json').symlink_to(outside)
        self.write('favicon.svg', 'x' * (2 * 1024 * 1024 + 1))
        self.write('mise.toml', 'broken = [')
        self.write('README.md', '# Heading\n\n**A useful description.**\n')
        snapshot = inspector.inspect(self.root)
        self.assertEqual(snapshot['name'], 'project')
        self.assertEqual(snapshot['description'], 'A useful description.')
        self.assertEqual(snapshot['icon'], '')
        self.assertIsNone(snapshot['git_root'])
        self.assertNotIn('JavaScript', [t['name'] for t in snapshot['technologies']])
        self.assertEqual(snapshot['mise']['tasks'], [])
        self.assertEqual(snapshot['mise']['tools'], [])

    def test_empty_git_repository_and_plain_folders_have_sensible_snapshots(self):
        self.init_git()
        state = inspector.inspect(self.root)['git']
        self.assertEqual(state['branch'], 'main')
        self.assertEqual(state['latest'], '')
        self.assertEqual(state['remote']['url'], '')
        nested = self.root / 'src'; nested.mkdir()
        self.assertEqual(inspector.inspect(nested)['path'], str(self.root))
        self.assertEqual(inspector.remote_info('git@github.com:org/repo.git')['url'], 'https://github.com/org/repo')
        self.assertEqual(inspector.remote_info('ssh://user@host:2222/org/repo.git')['url'], 'https://host/org/repo')
        self.assertFalse(inspector.remote_info('/local/repo')['url'])
        self.assertFalse(inspector.remote_info('ext::custom-command')['url'])


if __name__ == '__main__':
    unittest.main()
