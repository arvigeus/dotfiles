"""Steam ownership and native SCC profile checks, without host input injection."""

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / 'modules/hardware/peripherals/steam-controller'
SOURCE = MODULE / 'files/usr/local/bin/steam-controller-desktop'
PROFILE = MODULE / 'files/usr/local/share/dotfiles/steam-controller/Desktop.sccprofile'
LOADER = importlib.machinery.SourceFileLoader('steam_controller', str(SOURCE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
controller = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(controller)


class SteamControllerTests(unittest.TestCase):
    def test_client_detection_ignores_helpers_zombies_and_other_users(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)

            def process(pid, name, state='S'):
                path = proc / str(pid)
                path.mkdir(exist_ok=True)
                (path / 'comm').write_text(name + '\n')
                (path / 'stat').write_text(f'{pid} ({name}) {state} 1 2 3\n')

            process(1, 'steamwebhelper')
            process(2, 'steam', 'Z')
            (proc / 'self').mkdir()
            (proc / '3').mkdir()  # Exiting process with unreadable metadata.
            self.assertFalse(controller.steam_running(proc))
            process(4, 'steam')
            self.assertTrue(controller.steam_running(proc))
            self.assertFalse(controller.steam_running(proc, uid=os.getuid() + 1))
            (proc / '4/comm').unlink()
            self.assertFalse(controller.steam_running(proc))

    def test_handoff_stops_owned_mapper_before_reclaim_and_cleans_up(self):
        stopped = threading.Event()
        events = []
        states = iter((False, True, True, False))
        children = []

        def steam():
            state = next(states)
            events.append(('steam', state))
            return state

        def launch(command, **kwargs):
            child = Mock(returncode=None)
            child.poll.return_value = None
            children.append(child)
            events.append(('start', len(children)))
            self.assertEqual(command, [sys.executable, str(SOURCE), 'mapper'])
            self.assertTrue(kwargs['start_new_session'])
            self.assertEqual(kwargs['env'], {'fixture': 'yes'})
            return child

        def stop(child):
            events.append(('stop', children.index(child) + 1))

        def wait(_seconds):
            if len(children) == 2:
                stopped.set()

        with (
            patch.object(stopped, 'wait', side_effect=wait),
            patch.object(controller, 'stop_mapper', side_effect=stop),
        ):
            controller.supervise(stopped, {'fixture': 'yes'}, steam, launch)
        self.assertEqual(
            events,
            [
                ('steam', False),
                ('start', 1),
                ('steam', True),
                ('stop', 1),
                ('steam', True),
                ('steam', False),
                ('start', 2),
                ('stop', 2),
            ],
        )

    def test_existing_steam_client_prevents_mapper_start(self):
        stopped = threading.Event()
        launch = Mock()
        with patch.object(stopped, 'wait', side_effect=lambda _: stopped.set()):
            controller.supervise(stopped, {}, lambda: True, launch)
        launch.assert_not_called()

    def test_mapper_crash_fails_supervisor_for_systemd_retry(self):
        child = Mock(returncode=7)
        child.poll.return_value = 7
        with patch.object(controller, 'stop_mapper') as stop:
            with self.assertRaisesRegex(RuntimeError, 'status 7'):
                controller.supervise(
                    threading.Event(), {}, lambda: False, Mock(return_value=child)
                )
        stop.assert_called_once_with(child)

    def test_driver_loop_failure_exits_after_cleanup_instead_of_reinitializing(self):
        calls = []

        class SCCFixture:
            def run(self):
                calls.append('run')
                raise RuntimeError('device disappeared during reconnect')

            def sigterm(self):
                calls.append('release-devices')
                raise SystemExit(0)

        class Managed(controller.ExitOnMapperFailure, SCCFixture):
            pass

        with self.assertLogs(controller.LOG, level='ERROR'):
            with self.assertRaises(SystemExit) as exit:
                Managed().run()
        self.assertEqual(exit.exception.code, 1)
        self.assertEqual(calls, ['run', 'release-devices'])

    def test_normal_mapper_shutdown_keeps_its_success_status(self):
        class SCCFixture:
            def run(self):
                raise SystemExit(0)

        class Managed(controller.ExitOnMapperFailure, SCCFixture):
            pass

        with self.assertRaises(SystemExit) as exit:
            Managed().run()
        self.assertEqual(exit.exception.code, 0)

    def test_shutdown_allows_release_then_kills_an_unresponsive_group(self):
        child = Mock(pid=123)
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('fixture', 5), 0]
        with (
            patch.object(controller.os, 'killpg') as kill,
            self.assertLogs(controller.LOG, level='ERROR'),
        ):
            controller.stop_mapper(child)
        self.assertEqual(
            kill.call_args_list,
            [((123, signal.SIGKILL),)],
        )
        child.terminate.assert_called_once_with()
        self.assertEqual(child.wait.call_count, 2)

    @unittest.skipUnless(importlib.util.find_spec('scc'), 'SC Controller not installed')
    def test_native_profile_and_driver_scope(self):
        # Imports and SCC's configuration writes are isolated from the user's GUI.
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    'python3',
                    str(REPO / 'tests/fixtures/steam_controller_profile.py'),
                    str(SOURCE),
                    str(PROFILE),
                    directory,
                ],
                env=dict(os.environ, XDG_CONFIG_HOME=directory),
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('OK', result.stderr)


if __name__ == '__main__':
    unittest.main()
