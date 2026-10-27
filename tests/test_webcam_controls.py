"""V4L2 readback and mutation checks without accessing camera hardware."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

BACKEND = (
    Path(__file__).resolve().parents[1]
    / 'modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop/drawers/capture/webcam.py'
)
SPEC = importlib.util.spec_from_file_location('desktop_webcam', BACKEND)
webcam = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(webcam)

CONTROLS = """User Controls
                     brightness 0x00980900 (int) : min=-64 max=64 step=2 default=0 value=12
            white_balance_automatic 0x0098090c (bool) : default=1 value=1
      white_balance_temperature 0x0098091a (int) : min=2800 max=6500 step=1 default=4600 value=4600 flags=inactive
Camera Controls
                  auto_exposure 0x009a0901 (menu) : min=0 max=3 default=3 value=3
                                1: Manual Mode
                                3: Aperture Priority Mode
                        privacy 0x009a0910 (bool) : default=0 value=1 flags=read-only
                 unknown_vendor 0x009a0999 (int) : min=0 max=255 step=1 default=0 value=0
"""


class WebcamTests(unittest.TestCase):
    def test_supported_controls_menus_and_readonly_privacy(self):
        rows = {row['key']: row for row in webcam.parse_controls(CONTROLS)}
        self.assertEqual(rows['brightness']['minimum'], -64)
        self.assertEqual(rows['brightness']['step'], 2)
        self.assertEqual(
            rows['auto_exposure']['choices'],
            [
                dict(value=1, label='Manual Mode'),
                dict(value=3, label='Aperture Priority Mode'),
            ],
        )
        self.assertFalse(rows['privacy']['writable'])
        self.assertEqual(rows['privacy']['value'], 1)
        self.assertFalse(rows['white_balance_temperature']['writable'])
        self.assertNotIn('unknown_vendor', rows)

    def test_mutations_validate_fresh_hardware_state_before_writing(self):
        request = dict(
            op='set', device='/dev/video0', token='current', key='brightness', value=14
        )
        with (
            patch.object(webcam, 'identity', return_value='current'),
            patch.object(webcam, 'command', return_value=CONTROLS) as command,
        ):
            result = webcam.handle(request)
        self.assertEqual(result['token'], 'current')
        self.assertEqual(
            command.call_args_list[1].args,
            ('/dev/video0', '--set-ctrl', 'brightness=14'),
        )
        for changed in (
            {'token': 'stale'},
            {'key': 'privacy', 'value': 0},
            {'key': 'white_balance_temperature', 'value': 4500},
            {'value': 100},
            {'value': 13},
            {'value': True},
            {'key': 'auto_exposure', 'value': 2},
            {'key': 'other', 'value': 0},
        ):
            with (
                self.subTest(changed=changed),
                patch.object(webcam, 'identity', return_value='current'),
                patch.object(webcam, 'command', return_value=CONTROLS) as command,
            ):
                with self.assertRaises(ValueError):
                    webcam.handle(dict(request, **changed))
                self.assertEqual(command.call_count, 1)

    def test_replaced_device_and_unsupported_paths_never_mutate(self):
        request = dict(
            op='set', device='/dev/video0', token='old', key='brightness', value=14
        )
        with (
            patch.object(webcam, 'identity', return_value='new'),
            patch.object(webcam, 'command', return_value=CONTROLS) as command,
        ):
            with self.assertRaisesRegex(ValueError, 'changed'):
                webcam.handle(request)
            self.assertEqual(command.call_count, 1)
        for device in ('/dev/null', '/tmp/video0', '/dev/video0;echo fail', None):
            with self.subTest(device=device), self.assertRaises(ValueError):
                webcam.identity(device)


if __name__ == '__main__':
    unittest.main()
