"""System update launcher without package updates."""

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

    def test_update_preserves_literal_topgrade_arguments(self):
        self.program('topgrade')
        result = subprocess.run(
            [str(UPDATE), '--config', 'space ; $(literal).toml'],
            env=self.env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(), ['--config', 'space ; $(literal).toml']
        )
