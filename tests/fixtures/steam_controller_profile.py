"""Exercise installed SCC actions using recording devices, never real uinput."""

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

source, profile_path, runtime = sys.argv[1:]
loader = importlib.machinery.SourceFileLoader('controller', source)
spec = importlib.util.spec_from_loader(loader.name, loader)
controller = importlib.util.module_from_spec(spec)
loader.exec_module(controller)
environment = controller.mapper_environment(Path(runtime))
os.environ.update(environment)

from scc.actions import MouseAction
from scc.constants import SCButtons, SCPads, SCSticks, SCTriggers
from scc.mapper import Mapper
from scc.parser import ActionParser
from scc.profile import Profile
from scc.uinput import Dummy, Keyboard, Keys


class Clock:
    def __init__(self):
        self.now = 0
        self.tasks = []

    def schedule(self, delay, callback, *args):
        task = SimpleNamespace(at=self.now + delay, callback=callback, args=args)
        self.tasks.append(task)
        return task

    def cancel_task(self, task):
        self.tasks = [current for current in self.tasks if current is not task]

    def advance(self, seconds, mapper):
        target = self.now + seconds
        while self.tasks:
            task = min(self.tasks, key=lambda item: item.at)
            if task.at > target:
                break
            self.tasks.remove(task)
            self.now = task.at
            task.callback(*task.args)
            mapper.generate_events()
        self.now = target


class RecordingDevice(Dummy):
    def __init__(self):
        self.presses = []
        self.held = set()

    def pressEvent(self, keys):
        self.presses.append(tuple(keys))
        self.held.update(keys)

    def releaseEvent(self, keys):
        self.held.difference_update(keys)

    def keyEvent(self, key, value):
        if value:
            self.pressEvent([key])
        else:
            self.releaseEvent([key])


class RecordingKeyboard(Keyboard):
    """Run SCC's real scan-code translation without creating a uinput device."""

    def __init__(self):
        self._pressed = set()
        self.presses = []
        self.scans = []

    @property
    def held(self):
        return self._pressed

    def pressEvent(self, keys):
        self.presses.append(tuple(keys))
        super().pressEvent(keys)

    def scanEvent(self, value):
        self.scans.append(value)

    def keyEvent(self, key, value):
        pass

    def synEvent(self):
        pass


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = Profile(ActionParser()).load(profile_path)
        self.profile.compress()
        self.clock = Clock()
        self.mapper = Mapper(
            self.profile, self.clock, keyboard=None, mouse=None, gamepad=False
        )
        self.mapper.keyboard = RecordingKeyboard()
        self.mapper.mouse = RecordingDevice()
        self.special = []
        self.mapper.set_special_actions_handler(
            SimpleNamespace(
                on_sa_keyboard=lambda *_: self.special.append('keyboard'),
                on_sa_turnoff=lambda *_: self.special.append('turnoff'),
            )
        )

    def change(self, name, pressed):
        button = SCButtons[name]
        self.mapper.old_buttons = self.mapper.buttons
        if pressed:
            self.mapper.buttons |= button
        else:
            self.mapper.buttons &= ~button
        action = self.profile.buttons[button]
        if action:
            handler = action.button_press if pressed else action.button_release
            handler(self.mapper)
        self.mapper.generate_events()

    def tap(self, name):
        self.change(name, True)
        self.clock.advance(0.05, self.mapper)
        self.change(name, False)
        self.clock.advance(0.1, self.mapper)

    def tearDown(self):
        self.assertFalse(self.mapper.pressed, 'SCC has unreleased virtual keys')
        self.assertFalse(self.mapper.keyboard.held, 'Keyboard modifier was left held')
        self.assertFalse(self.mapper.mouse.held, 'Mouse button was left held')

    def test_center_buttons_emit_the_desktop_shortcuts(self):
        for name in ('C', 'BACK', 'START'):
            self.tap(name)
        self.assertEqual(
            self.mapper.keyboard.presses,
            [
                (Keys.KEY_LEFTMETA, Keys.KEY_R),
                (Keys.KEY_LEFTSHIFT, Keys.KEY_TAB),
                (Keys.KEY_LEFTCTRL, Keys.KEY_LEFTSHIFT, Keys.KEY_TAB),
            ],
        )
        self.assertEqual(self.special, [])

    def test_long_steam_press_only_powers_off(self):
        self.change('C', True)
        self.clock.advance(1.6, self.mapper)
        self.change('C', False)
        self.clock.advance(0.1, self.mapper)
        self.assertEqual(self.special, ['turnoff'])
        self.assertEqual(self.mapper.keyboard.presses, [])

    def test_bumpers_route_contextually_and_grips_resize(self):
        for name in ('LB', 'RB', 'LGRIP', 'RGRIP'):
            self.tap(name)
        self.assertEqual(
            self.mapper.keyboard.presses,
            [
                (Keys.KEY_LEFTMETA, Keys.KEY_F11),
                (Keys.KEY_LEFTMETA, Keys.KEY_F12),
                (Keys.KEY_LEFTMETA, Keys.KEY_LEFTBRACE),
                (Keys.KEY_LEFTMETA, Keys.KEY_RIGHTBRACE),
            ],
        )

    def test_y_switches_workspaces_moves_windows_and_maximizes(self):
        self.change('Y', True)
        for name in ('LB', 'RB', 'LGRIP', 'RGRIP', 'LSTICKPRESS'):
            self.tap(name)
        self.change('Y', False)
        self.assertEqual(
            self.mapper.keyboard.presses,
            [
                (Keys.KEY_LEFTMETA, Keys.KEY_LEFTCTRL, Keys.KEY_UP),
                (Keys.KEY_LEFTMETA, Keys.KEY_LEFTCTRL, Keys.KEY_DOWN),
                (Keys.KEY_LEFTMETA, Keys.KEY_LEFTCTRL, Keys.KEY_LEFTSHIFT, Keys.KEY_UP),
                (
                    Keys.KEY_LEFTMETA,
                    Keys.KEY_LEFTCTRL,
                    Keys.KEY_LEFTSHIFT,
                    Keys.KEY_DOWN,
                ),
                (Keys.KEY_LEFTMETA, Keys.KEY_M),
            ],
        )
        self.assertEqual(self.special, [])

    def test_releasing_y_first_releases_the_original_chord(self):
        self.change('Y', True)
        self.change('LGRIP', True)
        self.change('Y', False)
        self.change('LGRIP', False)
        self.assertEqual(len(self.mapper.keyboard.presses), 1)

    def test_confirm_cancel_play_and_keyboard(self):
        for name in ('A', 'B', 'X', 'LSTICKPRESS'):
            self.tap(name)
        self.assertEqual(
            self.mapper.keyboard.presses,
            [(Keys.KEY_ENTER,), (Keys.KEY_ESC,), (Keys.KEY_SPACE,)],
        )
        self.assertEqual(self.special, ['keyboard'])

    def test_mouse_buttons_use_supported_outputs(self):
        for name in ('LPAD', 'RPAD'):
            self.tap(name)
        for trigger in (SCTriggers.LT, SCTriggers.RT):
            action = self.profile.triggers[trigger]
            action.trigger(self.mapper, 255, 0)
            action.trigger(self.mapper, 0, 255)
        self.assertEqual(
            self.mapper.mouse.presses,
            [(Keys.BTN_MIDDLE,), (Keys.BTN_LEFT,), (Keys.BTN_RIGHT,), (Keys.BTN_LEFT,)],
        )

    def test_both_scroll_axes_are_reversed(self):
        actions = [
            action
            for action in self.profile.pads[SCPads.LPAD].get_all_actions()
            if isinstance(action, MouseAction)
        ]
        self.assertEqual(len(actions), 2)
        for action in actions:
            action.add(self.mapper, 1000, 0)
        self.assertEqual(self.mapper.mouse_movements[2:4], [-1000, 1000])

    def stick(self, x, y):
        self.profile.lstick.whole(self.mapper, x, y, SCSticks.LSTICK)
        self.mapper.generate_events()

    def test_full_stick_deflection_stays_held_at_the_edge(self):
        for key, points in (
            (Keys.KEY_UP, [(0, 16000), (0, 32767), (900, 32767)]),
            (Keys.KEY_DOWN, [(0, -16000), (0, -32768), (900, -32768)]),
            (Keys.KEY_LEFT, [(-16000, 0), (-32768, 0), (-32768, 900)]),
            (Keys.KEY_RIGHT, [(16000, 0), (32767, 0), (32767, 900)]),
        ):
            with self.subTest(key=key):
                before = len(self.mapper.keyboard.presses)
                for _ in range(4):
                    for x, y in points:
                        self.stick(x, y)
                        self.assertEqual(self.mapper.keyboard.held, {key})
                self.assertEqual(len(self.mapper.keyboard.presses), before + 1)
                self.stick(0, 0)
                self.assertFalse(self.mapper.keyboard.held)

    def test_y_stick_selects_controls_and_cleans_up_on_mode_release(self):
        self.change('Y', True)
        self.stick(-32768, 0)
        self.assertEqual(self.mapper.keyboard.held, {Keys.KEY_LEFTMETA, Keys.KEY_F9})
        self.stick(0, 0)
        self.stick(32767, 900)
        self.assertEqual(self.mapper.keyboard.held, {Keys.KEY_LEFTMETA, Keys.KEY_F10})
        self.change('Y', False)
        self.stick(32767, 0)
        self.assertEqual(self.mapper.keyboard.held, {Keys.KEY_RIGHT})
        self.stick(0, 0)

    def test_driver_scope(self):
        config = json.loads((Path(runtime) / 'scc/config.json').read_text())
        self.assertEqual(
            {name for name, enabled in config['drivers'].items() if enabled},
            {'sc_by_cable', 'sc_dongle', 'sc_by_bt'},
        )


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
