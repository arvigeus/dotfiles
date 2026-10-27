"""Optional private integrations without package updates or real agent execution."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
UPDATE = REPO / 'modules/system/package/topgrade/files/usr/local/bin/system-update'


class MaintenanceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + ':/usr/bin:/bin')

    def program(self, name):
        path = self.bin / name
        path.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        path.chmod(0o755)

    def test_update_prefers_private_agent_and_preserves_literal_arguments(self):
        self.program('system-agent')
        self.program('topgrade')
        result = subprocess.run([str(UPDATE), '--config', 'space ; $(literal).toml'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['update', '--config', 'space ; $(literal).toml'])

    def test_update_uses_native_topgrade_when_private_project_is_absent(self):
        self.program('topgrade')
        result = subprocess.run([str(UPDATE), '--no-ask-retry'], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['--no-ask-retry'])

    def test_backup_passes_existing_options_through_private_lock_wrapper(self):
        self.program('system-agent')
        result = subprocess.run([str(REPO/'backup.sh'), '--dry-run', '--destination', str(self.root/'private')],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['--dotfiles', str(REPO), 'backup', '--',
                                                     '--dry-run', '--destination', str(self.root/'private')])
        self.assertFalse((self.root/'private').exists())
