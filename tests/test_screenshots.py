"""Exercise screenshot/editor handoff without capturing the desktop."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'modules/desktop/hyprland/files/usr/local/bin/desktop-screenshot'


class ScreenshotTests(unittest.TestCase):
    def run_capture(self, mode='edit', options=(), expected_status=0, details=False, preference=None, save_preference=None, **settings):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / 'bin'
            commands.mkdir()
            if preference is not None or save_preference is not None:
                config = root / 'config/quickshell/desktop'
                config.mkdir(parents=True)
                if preference is not None:
                    (config / 'screenshot-editor').write_text(preference + '\n')
                if save_preference is not None:
                    (config / 'screenshot-save').write_text(save_preference + '\n')
            # Shell metacharacters in XDG paths must stay literal arguments.
            pictures = root / 'Pictures with spaces; $dollars'
            log = root / 'editor.json'
            programs = {
                'xdg-user-dir': '#!/bin/sh\nprintf "%s\\n" "$PICTURES"\n',
                'hyprshot': '''#!/usr/bin/env python3
import os, subprocess, sys
args = sys.argv[1:]
if os.environ.get('CAPTURE_LOG'):
    import json, pathlib
    pathlib.Path(os.environ['CAPTURE_LOG']).write_text(json.dumps(args))
if os.environ.get('CANCEL'):
    sys.exit(0)
if '--raw' in args:
    subprocess.Popen([sys.executable, '-c',
        'import sys,time; time.sleep(.1); sys.stdout.buffer.write(bytes([137,80,78,71,13,10,26,10])+b"image")'])
    sys.exit(int(os.environ.get('MONITOR_STATUS', '0')))
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
                'notify-send': '#!/bin/sh\ntouch "$NOTICE_LOG"\n',
                'wl-copy': '#!/usr/bin/env python3\nimport os,pathlib,sys\npathlib.Path(os.environ["CLIPBOARD_LOG"]).write_bytes(sys.stdin.buffer.read())\n',
            }
            programs['satty'] = programs['ksnip'].replace('sys.argv[-1]', "sys.argv[sys.argv.index('--filename') + 1]")
            for name, source in programs.items():
                command = commands / name
                command.write_text(source)
                command.chmod(0o755)
            env = dict(os.environ, PATH=str(commands) + ':' + os.environ['PATH'],
                       HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'), PICTURES=str(pictures), EDITOR_LOG=str(log))
            env['CAPTURE_LOG'] = str(root / 'capture.json')
            env['CLIPBOARD_LOG'] = str(root / 'clipboard.png')
            env['NOTICE_LOG'] = str(root / 'notification')
            env.pop('DESKTOP_SCREENSHOT_EDITOR', None)
            env.update(settings)
            result = subprocess.run(['bash', str(SCRIPT), mode, *options], env=env,
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, expected_status, result.stderr)
            if details:
                if '--edit' in options and expected_status == 0:
                    # Report mode launches the editor independently of capture.
                    for _ in range(100):
                        if log.exists():
                            break
                        time.sleep(.01)
                return dict(result=result, args=json.loads((root / 'capture.json').read_text()),
                            editor=json.loads(log.read_text()) if log.exists() else None,
                            saved=list(pictures.rglob('*.png')),
                            clipboard=(root / 'clipboard.png').read_bytes() if (root / 'clipboard.png').exists() else None,
                            notified=(root / 'notification').exists())
            return json.loads(log.read_text()) if log.exists() else None

    def test_editor_waits_for_capture_and_receives_literal_path(self):
        command = self.run_capture()
        self.assertEqual(Path(command[0]).name, 'ksnip')
        self.assertEqual(command[1], '--edit')
        self.assertIn('Pictures with spaces; $dollars/Screenshots/', command[2])

    def test_cancellation_and_raw_capture_skip_editor(self):
        self.assertIsNone(self.run_capture(CANCEL='1'))
        self.assertIsNone(self.run_capture('region', options=['--no-edit']))

    def test_successful_capture_survives_hyprshot_monitor_failure(self):
        command = self.run_capture(MONITOR_STATUS='1')
        self.assertEqual(Path(command[0]).name, 'ksnip')

    def test_previous_editor_remains_available(self):
        command = self.run_capture(DESKTOP_SCREENSHOT_EDITOR='satty')
        self.assertEqual(Path(command[0]).name, 'satty')
        self.assertEqual(command[command.index('--filename') + 1],
                         command[command.index('--output-filename') + 1])

    def test_drawer_captures_named_display_and_reports_image(self):
        capture = self.run_capture('output', options=['--output', 'DP-2', '--report', '--edit'], details=True)
        self.assertEqual(capture['args'][:2], ['-m', 'output'])
        self.assertIn('DP-2', capture['args'])
        self.assertIn('--silent', capture['args'])
        self.assertNotIn('active', capture['args'])
        self.assertEqual(capture['result'].stdout.strip(), capture['editor'][2])

    def test_whole_display_failure_does_not_look_like_selection_cancellation(self):
        capture = self.run_capture('output', options=['--report'], details=True, expected_status=1, CANCEL='1')
        self.assertEqual(capture['result'].stdout, '')
        self.assertIn('Could not capture', capture['result'].stderr)

    def test_shared_preference_controls_region_and_display_captures(self):
        self.assertIsNone(self.run_capture('region', preference='off'))
        self.assertIsNone(self.run_capture('output', preference='off'))
        self.assertIsNotNone(self.run_capture('region', preference='on'))
        self.assertIsNotNone(self.run_capture('output', preference='on'))
        self.assertIsNotNone(self.run_capture('region'))  # Preserve shortcut's default.

    def test_explicit_overrides_freeze_drawer_choice_and_keep_raw_shortcut(self):
        self.assertIsNotNone(self.run_capture('region', preference='off', options=['--edit']))
        self.assertIsNone(self.run_capture('region', preference='on', options=['--no-edit']))

    def test_clipboard_only_is_global_silent_and_writes_no_image(self):
        for mode in ('region', 'output', 'active-window'):
            with self.subTest(mode=mode):
                capture = self.run_capture(mode, save_preference='off', preference='on', options=['--report'], details=True)
                self.assertIn('--raw', capture['args'])
                self.assertIn('--silent', capture['args'])
                self.assertNotIn('-o', capture['args'])
                self.assertFalse(capture['saved'])
                self.assertIsNone(capture['editor'])
                self.assertFalse(capture['notified'])
                self.assertTrue(capture['clipboard'].startswith(b'\x89PNG'))
                self.assertEqual(capture['result'].stdout.strip(), 'clipboard')

    def test_clipboard_cancellation_does_not_replace_clipboard_or_notify(self):
        capture = self.run_capture('region', save_preference='off', CANCEL='1', details=True)
        self.assertIsNone(capture['clipboard'])
        self.assertFalse(capture['saved'])
        self.assertFalse(capture['notified'])
        capture = self.run_capture('output', save_preference='off', CANCEL='1', details=True, expected_status=1)
        self.assertFalse(capture['notified'])

    def test_explicit_save_override_and_clipboard_survives_monitor_failure(self):
        capture = self.run_capture('region', save_preference='off', options=['--save', '--no-edit'], details=True)
        self.assertTrue(capture['saved'])
        capture = self.run_capture('output', options=['--no-save', '--report', '--edit'], MONITOR_STATUS='1', details=True)
        self.assertEqual(capture['result'].stdout.strip(), 'clipboard')
        self.assertFalse(capture['saved'])
        self.assertIsNone(capture['editor'])


if __name__ == '__main__':
    unittest.main()
