"""Exercise screenshot/editor handoff without capturing the desktop."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'modules/desktop/hyprland/files/usr/local/bin/desktop-screenshot'


class ScreenshotTests(unittest.TestCase):
    def run_capture(self, mode='edit', **settings):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / 'bin'
            commands.mkdir()
            # Shell metacharacters in XDG paths must stay literal arguments.
            pictures = root / 'Pictures with spaces; $dollars'
            log = root / 'editor.json'
            programs = {
                'xdg-user-dir': '#!/bin/sh\nprintf "%s\\n" "$PICTURES"\n',
                'hyprshot': '''#!/usr/bin/env python3
import os, subprocess, sys
args = sys.argv[1:]
if os.environ.get('CANCEL'):
    sys.exit(0)
image = os.path.join(args[args.index('-o') + 1], args[args.index('-f') + 1])
# Match Hyprshot's fork: parent exits before the child writes the screenshot.
subprocess.Popen([sys.executable, '-c',
    'import pathlib, sys, time; time.sleep(.1); pathlib.Path(sys.argv[1]).write_bytes(b"image")', image])
sys.exit(int(os.environ.get('MONITOR_STATUS', '0')))
''',
                'ksnip': '''#!/usr/bin/env python3
import json, os, pathlib, sys
image = pathlib.Path(sys.argv[-1])
assert image.read_bytes() == b'image'
pathlib.Path(os.environ['EDITOR_LOG']).write_text(json.dumps(sys.argv))
''',
                'notify-send': '#!/bin/sh\nexit 0\n',
            }
            programs['satty'] = programs['ksnip'].replace('sys.argv[-1]', "sys.argv[sys.argv.index('--filename') + 1]")
            for name, source in programs.items():
                command = commands / name
                command.write_text(source)
                command.chmod(0o755)
            env = dict(os.environ, PATH=str(commands) + ':' + os.environ['PATH'],
                       HOME=str(root), PICTURES=str(pictures), EDITOR_LOG=str(log))
            env.pop('DESKTOP_SCREENSHOT_EDITOR', None)
            env.update(settings)
            result = subprocess.run(['bash', str(SCRIPT), mode], env=env,
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(log.read_text()) if log.exists() else None

    def test_editor_waits_for_capture_and_receives_literal_path(self):
        command = self.run_capture()
        self.assertEqual(Path(command[0]).name, 'ksnip')
        self.assertEqual(command[1], '--edit')
        self.assertIn('Pictures with spaces; $dollars/Screenshots/', command[2])

    def test_cancellation_and_raw_capture_skip_editor(self):
        self.assertIsNone(self.run_capture(CANCEL='1'))
        self.assertIsNone(self.run_capture('region'))

    def test_successful_capture_survives_hyprshot_monitor_failure(self):
        command = self.run_capture(MONITOR_STATUS='1')
        self.assertEqual(Path(command[0]).name, 'ksnip')

    def test_previous_editor_remains_available(self):
        command = self.run_capture(DESKTOP_SCREENSHOT_EDITOR='satty')
        self.assertEqual(Path(command[0]).name, 'satty')
        self.assertEqual(command[command.index('--filename') + 1],
                         command[command.index('--output-filename') + 1])


if __name__ == '__main__':
    unittest.main()
