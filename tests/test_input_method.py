"""Input-method controller error contract and read-only status, with every
session, compositor and Fcitx command replaced by a recording fake."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CONTROLLER = (
    REPO / 'modules/hardware/keyboard/input-method/files/usr/local/bin/input-method'
)
FAKE = """#!/bin/bash
printf '%s\\n' "$(basename "$0") $*" >> "$FAKE_LOG"
case "$(basename "$0") $1 $2" in
    "hyprctl eval"*)
        if [[ -n ${FAKE_HYPRCTL_FAIL:-} ]]; then echo 'hyprctl: boom' >&2; exit 1; fi ;;
    "hyprctl -j devices")
        echo '{"keyboards":[{"name":"laptop","main":true,"layout":"us,bg","active_layout_index":1}]}' ;;
    "gdbus call"*) echo '(false,)' ;;
    "systemctl --user show") echo loaded ;;
esac
"""


class ControllerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        tools = self.root / 'bin'
        tools.mkdir()
        for name in (
            'gdbus',
            'systemctl',
            'hyprctl',
            'fcitx5',
            'fcitx5-remote',
            'notify-send',
        ):
            (tools / name).write_text(FAKE)
            (tools / name).chmod(0o755)
        self.log = self.root / 'calls.log'
        self.log.touch()
        self.env = dict(
            PATH=f'{tools}:/usr/bin:/bin',
            HOME=str(self.root),
            XDG_CONFIG_HOME=str(self.root / 'config'),
            XDG_DATA_HOME=str(self.root / 'data'),
            XDG_DATA_DIRS=str(self.root / 'share'),
            XDG_RUNTIME_DIR=str(self.root / 'run'),
            HYPRLAND_INSTANCE_SIGNATURE='a/b',
            FAKE_LOG=str(self.log),
        )
        (self.root / 'run').mkdir()

    def control(self, *args, **env):
        return subprocess.run(
            ['bash', str(CONTROLLER), *args],
            env=dict(self.env, **env),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def calls(self, tool):
        return [
            line.split(' ', 1)[1]
            for line in self.log.read_text().splitlines()
            if line.split(' ', 1)[0] == tool
        ]

    def test_stated_reason_is_the_only_error_line_and_the_notification(self):
        result = self.control('select', 'vi', '--notify')
        reason = (
            'Vietnamese Telex requires Fcitx5, UniKey and the vietnamese user service'
        )
        self.assertEqual((result.returncode, result.stderr), (1, reason + '\n'))
        self.assertEqual(
            self.calls('notify-send'),
            [f'Input method Could not change input language. {reason}'],
        )
        self.assertEqual(self.calls('systemctl'), [])

    def test_failed_command_keeps_its_own_output_first(self):
        result = self.control('select', 'bg', '--notify', FAKE_HYPRCTL_FAIL='1')
        lines = result.stderr.splitlines()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(lines[0], 'hyprctl: boom')
        self.assertTrue(lines[1].startswith('Input method failed: '))
        self.assertEqual(
            self.calls('notify-send'),
            ['Input method Could not change input language. ' + lines[1]],
        )

    def test_status_reads_the_event_keyboard_without_changing_anything(self):
        engine = self.root / 'share/fcitx5/inputmethod/unikey.conf'
        engine.parent.mkdir(parents=True)
        engine.touch()
        result = self.control('status', 'laptop')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(
            json.loads(result.stdout),
            dict(available=True, secondary='bg', language='bg', running=False),
        )
        self.assertEqual(
            self.calls('systemctl'),
            ['--user show vietnamese.service --property=LoadState --value'],
        )
        self.assertEqual(self.calls('hyprctl'), ['-j devices'])
        self.assertEqual(os.listdir(self.root / 'run'), [])


if __name__ == '__main__':
    unittest.main()
