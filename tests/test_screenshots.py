"""Exercise grim/slurp capture and editor handoff without capturing the desktop."""
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
                'slurp': '''#!/usr/bin/env python3
import json, os, pathlib, sys
pathlib.Path(os.environ['SLURP_LOG']).write_text(json.dumps([sys.argv[1:], sys.stdin.read() if '-r' in sys.argv else '']))
if os.environ.get('CANCEL'):
    sys.exit(1)
print('10,20 300x200')
''',
                'grim': '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
pathlib.Path(os.environ['CAPTURE_LOG']).write_text(json.dumps(args))
if os.environ.get('GRIM_FAIL'):
    sys.exit(1)
image = bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b'image'
if args[-1] == '-':
    sys.stdout.buffer.write(image)
else:
    pathlib.Path(args[-1]).write_bytes(b'image')
''',
                'hyprctl': '''#!/usr/bin/env python3
import json, sys
monitor = dict(id=0, name='DP-1', x=0, y=0, width=2000, height=1000, scale=2, transform=0, focused=True,
               activeWorkspace=dict(id=1), specialWorkspace=dict(id=0))
window = dict(mapped=True, hidden=False, monitor=0, workspace=dict(id=1), at=[900, 100], size=[400, 300])
hidden = dict(window, workspace=dict(id=2))
print(json.dumps(dict(monitors=[monitor], clients=[window, hidden], activewindow=window)[sys.argv[2]]))
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
            env['SLURP_LOG'] = str(root / 'slurp.json')
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
                capture = root / 'capture.json'
                return dict(result=result, args=json.loads(capture.read_text()) if capture.exists() else None,
                            slurp=json.loads((root / 'slurp.json').read_text()) if (root / 'slurp.json').exists() else None,
                            editor=json.loads(log.read_text()) if log.exists() else None,
                            saved=list(pictures.rglob('*.png')),
                            clipboard=(root / 'clipboard.png').read_bytes() if (root / 'clipboard.png').exists() else None,
                            notified=(root / 'notification').exists())
            return json.loads(log.read_text()) if log.exists() else None

    def test_editor_receives_literal_path_of_saved_capture(self):
        command = self.run_capture()
        self.assertEqual(Path(command[0]).name, 'ksnip')
        self.assertEqual(command[1], '--edit')
        self.assertIn('Pictures with spaces; $dollars/Screenshots/', command[2])

    def test_selection_precedes_capture_and_cancellation_changes_nothing(self):
        capture = self.run_capture('region', details=True)
        self.assertEqual(capture['slurp'][0], ['-d'])
        self.assertEqual(capture['args'][:2], ['-g', '10,20 300x200'])
        self.assertEqual(capture['clipboard'], b'image')
        for save in ('on', 'off'):
            capture = self.run_capture('region', save_preference=save, details=True, CANCEL='1')
            self.assertIsNone(capture['args'])
            self.assertIsNone(capture['clipboard'])
            self.assertFalse(capture['saved'] or capture['notified'] or capture['editor'])
        self.assertIsNone(self.run_capture('region', options=['--no-edit']))

    def test_windows_are_clipped_to_their_monitor(self):
        capture = self.run_capture('window', details=True)
        self.assertEqual(capture['slurp'], [['-r'], '900,100 100x300\n'])
        capture = self.run_capture('active-window', options=['--no-edit'], details=True)
        self.assertEqual(capture['args'][:2], ['-g', '900,100 100x300'])
        self.assertTrue(capture['notified'])

    def test_previous_editor_remains_available(self):
        command = self.run_capture(DESKTOP_SCREENSHOT_EDITOR='satty')
        self.assertEqual(Path(command[0]).name, 'satty')
        self.assertEqual(command[command.index('--filename') + 1],
                         command[command.index('--output-filename') + 1])

    def test_drawer_captures_named_display_and_reports_image(self):
        capture = self.run_capture('output', options=['--output', 'DP-2', '--report', '--edit'], details=True)
        self.assertEqual(capture['args'][:2], ['-o', 'DP-2'])
        self.assertEqual(capture['result'].stdout.strip(), capture['editor'][2])
        self.assertFalse(capture['notified'])
        capture = self.run_capture('output', options=['--no-edit'], details=True)
        self.assertEqual(capture['args'][:2], ['-o', 'DP-1'])

    def test_whole_display_failure_does_not_look_like_selection_cancellation(self):
        capture = self.run_capture('output', options=['--report'], details=True, expected_status=1, GRIM_FAIL='1')
        self.assertEqual(capture['result'].stdout, '')
        self.assertIn('Could not capture', capture['result'].stderr)
        self.assertFalse(capture['saved'])

    def test_shared_preference_controls_region_and_display_captures(self):
        self.assertIsNone(self.run_capture('region', preference='off'))
        self.assertIsNone(self.run_capture('output', preference='off'))
        self.assertIsNotNone(self.run_capture('region', preference='on'))
        self.assertIsNotNone(self.run_capture('output', preference='on'))
        self.assertIsNotNone(self.run_capture('region'))  # Preserve shortcut's default.

    def test_explicit_overrides_freeze_drawer_choice_and_keep_raw_shortcut(self):
        self.assertIsNotNone(self.run_capture('region', preference='off', options=['--edit']))
        self.assertIsNone(self.run_capture('region', preference='on', options=['--no-edit']))

    def test_clipboard_only_is_silent_and_writes_no_image(self):
        for mode in ('region', 'output', 'active-window'):
            with self.subTest(mode=mode):
                capture = self.run_capture(mode, save_preference='off', preference='on', options=['--report'], details=True)
                self.assertEqual(capture['args'][-1], '-')
                self.assertFalse(capture['saved'])
                self.assertIsNone(capture['editor'])
                self.assertFalse(capture['notified'])
                self.assertTrue(capture['clipboard'].startswith(b'\x89PNG'))
                self.assertEqual(capture['result'].stdout.strip(), 'clipboard')

    def test_failed_clipboard_capture_keeps_clipboard_and_does_not_notify(self):
        capture = self.run_capture('output', save_preference='off', details=True, expected_status=1, GRIM_FAIL='1')
        self.assertIsNone(capture['clipboard'])
        self.assertFalse(capture['notified'])

    def test_explicit_save_override(self):
        capture = self.run_capture('region', save_preference='off', options=['--save', '--no-edit'], details=True)
        self.assertTrue(capture['saved'])
        capture = self.run_capture('output', options=['--no-save', '--report', '--edit'], details=True)
        self.assertEqual(capture['result'].stdout.strip(), 'clipboard')
        self.assertFalse(capture['saved'])
        self.assertIsNone(capture['editor'])


if __name__ == '__main__':
    unittest.main()
