"""Exercise the real session supervisor with isolated compositor/client executables."""

import contextlib
import fcntl
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'modules/desktop/hyprland/files/usr/local/bin/session-mode'
LOADER = importlib.machinery.SourceFileLoader('session_modes', str(SOURCE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
modes = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(modes)
HOOK = REPO / 'modules/gaming/gamescope-session/files/usr/bin/steamos-session-select'
GAMING = REPO / 'modules/gaming/gamescope-session/files/usr/local/bin/gaming-session'


class SessionModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / 'bin'
        self.binary.mkdir()
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.drm = self.root / 'drm'
        self.drm.mkdir()
        self.drm_card('card0', '1002:73df', {'DP-1': 'connected'})
        self.state = self.runtime / 'session-mode'
        runner = self.binary / 'session-mode'
        runner.write_text(f"""#!/usr/bin/env python3
import importlib.machinery,importlib.util,os,sys
loader=importlib.machinery.SourceFileLoader('modes',{str(SOURCE)!r})
spec=importlib.util.spec_from_loader(loader.name,loader)
m=importlib.util.module_from_spec(spec);loader.exec_module(m)
m.STARTUP_TIMEOUT=float(os.environ.get('SESSION_TEST_STARTUP_TIMEOUT','.4'))
m.STOP_TIMEOUT=.2
sys.exit(m.main())
""")
        runner.chmod(0o755)
        stub = self.binary / 'fixture'
        stub.write_text("""#!/usr/bin/env python3
import os,signal,subprocess,sys,time
from pathlib import Path
root=Path(os.environ['SESSION_TEST_ROOT']);name=Path(sys.argv[0]).name
def log(text):
 with (root/'events').open('a') as output:output.write(text+'\\n')
def session(mode):
 status=Path('/proc/self/status').read_text().split('SigIgn:')[1].split()[0]
 ttou=int(status,16)>>signal.SIGTTOU-1&1
 with (root/'sessions').open('a') as output:output.write(f'{mode} {os.getpgrp()} {ttou}\\n')
 signal.signal(signal.SIGTERM,lambda *_:(log('term-'+mode),os._exit(143)))
 log(mode)
def wait_for_stop(mode):
 stop=root/('stop-'+mode)
 while not stop.exists():time.sleep(.02)
 stop.unlink()
if name=='uwsm':
 if sys.argv[1]=='start':
  session('desktop');wait_for_stop('desktop')
 elif sys.argv[1]=='stop':
  log('stop-desktop')
  queued=root/'request-during-stop'
  if queued.exists():
   subprocess.run(['session-mode',queued.read_text()],check=True);queued.unlink()
  if os.environ.get('SESSION_TEST_STOP_FAIL'):
   log('stop-desktop-failed');raise SystemExit(1)
  (root/'stop-desktop').touch()
elif name=='gaming-session':
 if sys.argv[1:]==['--check']:
  if os.environ.get('SESSION_TEST_CHECK_FAIL'):
   print('No connected display matches the configured GPU.',file=sys.stderr);raise SystemExit(1)
  raise SystemExit(0)
 session('gaming')
 scenario=os.environ.get('SESSION_TEST_GAME','ready')
 ready=int(os.environ['SESSION_MODE_READY_FD'])
 if scenario=='fail':raise SystemExit(42)
 if scenario=='closed':os.close(ready)
 elif scenario=='exited':os.write(ready,b'ready\\nexited\\n')
 elif scenario!='hang':os.write(ready,b'ready\\n')
 if scenario=='ready-closed':os.close(ready)
 wait_for_stop('gaming')
elif name=='systemd-cat':
 command=sys.argv[sys.argv.index('--')+1:];os.execvp(command[0],command)
elif name=='gamescope':
 # Gamescope 3.17 reports readiness, then starts its client without inherited FDs.
 args=sys.argv[1:];session('gaming')
 ready=os.open(args[args.index('--ready-fd')+1],os.O_WRONLY)
 os.write(ready,b':1 gamescope-0\\n');os.close(ready)
 subprocess.run(args[args.index('--')+1:])
 while os.environ.get('SESSION_TEST_GAMESCOPE_LINGER'):time.sleep(1)
elif name=='switcherooctl':
 os.execvp(sys.argv[2],sys.argv[2:])
elif name=='steam':
 if sys.argv[1:]==['-shutdown']:
  log('stop-gaming');(root/'stop-gaming').touch()
 else:
  log('steam');wait_for_stop('gaming');log('steam-exited')
""")
        stub.chmod(0o755)
        for name in (
            'uwsm',
            'gaming-session',
            'steam',
            'gamescope',
            'switcherooctl',
            'systemd-cat',
        ):
            (self.binary / name).symlink_to(stub)
        self.env = dict(
            os.environ,
            PATH=str(self.binary) + ':' + os.environ['PATH'],
            SESSION_TEST_ROOT=str(self.root),
            XDG_RUNTIME_DIR=str(self.runtime),
            SYSTEM_GAMING_DRM_ROOT=str(self.drm),
            SYSTEM_GAMING_SYSTEM_CONFIG='/nonexistent',
            SYSTEM_GAMING_USER_CONFIG='/nonexistent',
            PYTHONDONTWRITEBYTECODE='1',
        )
        self.process = None
        self.addCleanup(self.stop)

    def command(self, *args, check=True):
        return subprocess.run(
            [str(self.binary / 'session-mode'), *args],
            env=self.env,
            check=check,
            text=True,
            capture_output=True,
            timeout=5,
        )

    def drm_card(self, name, gpu, outputs):
        device = self.drm / name / 'device'
        device.mkdir(parents=True)
        vendor, device_id = gpu.split(':')
        (device / 'vendor').write_text('0x' + vendor + '\n')
        (device / 'device').write_text('0x' + device_id + '\n')
        for output, state in outputs.items():
            connector = self.drm / f'{name}-{output}'
            connector.mkdir()
            (connector / 'status').write_text(state + '\n')

    def gaming(self, *args, **settings):
        return subprocess.run(
            [str(GAMING), *args],
            env=dict(self.env, **settings),
            text=True,
            capture_output=True,
            timeout=5,
        )

    def start(self, **options):
        # Never hand the terminal running the tests to fixture sessions.
        options.setdefault('stdin', subprocess.DEVNULL)
        self.process = subprocess.Popen(
            [str(self.binary / 'session-mode'), 'run'],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **options,
        )

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.output = self.process.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.output = self.process.communicate()
                self.fail('Session owner did not terminate its fixture child')
            self.process = None

    def events(self):
        return (
            (self.root / 'events').read_text().splitlines()
            if (self.root / 'events').exists()
            else []
        )

    @contextlib.contextmanager
    def case(self, **parameters):
        # A failed case must not leave its supervisor holding the session lock.
        with self.subTest(**parameters):
            (self.root / 'events').unlink(missing_ok=True)
            try:
                yield
            finally:
                self.stop()

    def hook(self):
        subprocess.run([str(HOOK), 'plasma'], env=self.env, check=True, timeout=5)

    def sessions(self):
        lines = (self.root / 'sessions').read_text().splitlines()
        return [line.split() for line in lines]

    def wait_event(self, event, count=1):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.events().count(event) >= count:
                return
            if self.process and self.process.poll() is not None:
                out, err = self.process.communicate()
                self.fail(f'Owner exited: {out} {err}')
            time.sleep(0.03)
        self.fail(f'Missing {event} #{count}: {self.events()}')

    def test_desktop_gaming_return_hook_and_desktop_reload(self):
        self.start()
        self.wait_event('desktop')
        self.assertEqual(
            json.loads(self.command('status').stdout), dict(available=True, gaming=True)
        )
        self.command('gaming')
        self.wait_event('gaming')
        subprocess.run([str(HOOK), 'plasma'], env=self.env, check=True, timeout=5)
        self.wait_event('desktop', 2)
        self.command('desktop')
        self.wait_event('desktop', 3)
        self.assertEqual(
            self.events()[:7],
            [
                'desktop',
                'stop-desktop',
                'gaming',
                'stop-gaming',
                'desktop',
                'stop-desktop',
                'desktop',
            ],
        )
        self.assertFalse((self.state / 'next').exists())
        self.stop()
        self.assertEqual(
            self.events().count('desktop'), 3, 'stopping must not start another session'
        )

    def test_steam_exit_and_failed_gaming_start_return_to_desktop(self):
        for scenario in ('ready', 'fail'):
            with self.subTest(scenario=scenario):
                self.env['SESSION_TEST_GAME'] = scenario
                desktop_count = self.events().count('desktop')
                gaming_count = self.events().count('gaming')
                self.start()
                self.wait_event('desktop', desktop_count + 1)
                self.command('gaming')
                self.wait_event('gaming', gaming_count + 1)
                if scenario == 'ready':
                    (self.root / 'stop-gaming').touch()
                self.wait_event('desktop', desktop_count + 2)
                self.stop()

    def test_unready_gaming_returns_to_desktop_without_starting_steam(self):
        # `steam -shutdown` starts a client when none runs; Gamescope gets TERM.
        for scenario in ('hang', 'closed'):
            with self.case(scenario=scenario):
                self.env['SESSION_TEST_GAME'] = scenario
                self.start()
                self.wait_event('desktop')
                self.command('gaming')
                self.wait_event('gaming')
                self.wait_event('desktop', 2)
                self.stop()
                self.assertIn(
                    'Gaming startup timed out or closed its readiness pipe',
                    self.output[1],
                )
                self.assertEqual(
                    self.events(),
                    [
                        'desktop',
                        'stop-desktop',
                        'gaming',
                        'term-gaming',
                        'desktop',
                        'stop-desktop',
                    ],
                )

    def test_requests_and_logout_before_gaming_readiness_skip_steam_shutdown(self):
        self.env.update(SESSION_TEST_GAME='hang', SESSION_TEST_STARTUP_TIMEOUT='5')
        self.start()
        self.wait_event('desktop')
        self.command('gaming')
        self.wait_event('gaming')
        self.command('desktop')
        self.wait_event('desktop', 2)
        self.command('gaming')
        self.wait_event('gaming', 2)
        self.stop()
        self.assertEqual(
            self.events(),
            [
                'desktop',
                'stop-desktop',
                'gaming',
                'term-gaming',
                'desktop',
                'stop-desktop',
                'gaming',
                'term-gaming',
            ],
        )
        self.assertNotIn('timed out', self.output[1])

    def test_steam_exit_bounds_a_lingering_gamescope_through_the_real_launcher(self):
        (self.binary / 'gaming-session').unlink()
        (self.binary / 'gaming-session').symlink_to(GAMING)
        for linger, finish, expected in (
            ('1', lambda: (self.root / 'stop-gaming').touch(), ['term-gaming']),
            ('', lambda: self.hook(), ['stop-gaming']),
        ):
            with self.case(linger=bool(linger)):
                self.env['SESSION_TEST_GAMESCOPE_LINGER'] = linger
                self.start()
                self.wait_event('desktop')
                self.command('gaming')
                self.wait_event('steam')
                finish()
                self.wait_event('desktop', 2)
                self.stop()
                events = self.events()
                self.assertEqual(
                    events[:4], ['desktop', 'stop-desktop', 'gaming', 'steam']
                )
                self.assertEqual(events[-2:], ['desktop', 'stop-desktop'])
                self.assertCountEqual(events[4:-2], ['steam-exited', *expected])

    def test_steam_exit_reported_with_readiness_and_late_pipe_closure(self):
        for scenario, events in (
            ('exited', ['term-gaming']),
            ('ready-closed', ['stop-gaming']),
        ):
            with self.case(scenario=scenario):
                self.env['SESSION_TEST_GAME'] = scenario
                self.start()
                self.wait_event('desktop')
                self.command('gaming')
                self.wait_event('gaming')
                if scenario == 'ready-closed':
                    time.sleep(0.6)
                    self.assertEqual(
                        self.events(), ['desktop', 'stop-desktop', 'gaming']
                    )
                    self.hook()
                self.wait_event('desktop', 2)
                self.stop()
                self.assertEqual(
                    self.events(),
                    ['desktop', 'stop-desktop', 'gaming', *events]
                    + ['desktop', 'stop-desktop'],
                )

    def test_request_made_while_stopping_replaces_the_pending_transition(self):
        (self.root / 'request-during-stop').write_text('desktop')
        self.start()
        self.wait_event('desktop')
        self.command('gaming')
        self.wait_event('desktop', 2)
        self.stop()
        self.assertEqual(
            self.events(), ['desktop', 'stop-desktop', 'desktop', 'stop-desktop']
        )
        self.assertFalse((self.state / 'next').exists())

    def test_stop_skips_the_graceful_command_once_the_session_exited(self):
        supervisor = modes.Supervisor(self.state)
        self.addCleanup(os.close, supervisor.wake_read)
        self.addCleanup(os.close, supervisor.wake_write)
        supervisor.child = subprocess.Popen(['true'], process_group=0)
        os.waitid(os.P_PID, supervisor.child.pid, os.WEXITED | os.WNOWAIT)
        with patch.object(modes.subprocess, 'run') as run:
            supervisor.stop_child(['steam', '-shutdown'])
        run.assert_not_called()
        self.assertEqual(supervisor.child.returncode, 0)

    def test_terminal_follows_each_session_without_ignoring_job_control(self):
        master, terminal = os.openpty()
        self.addCleanup(os.close, master)
        try:
            self.start(
                stdin=terminal,
                start_new_session=True,
                preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
            )
        finally:
            os.close(terminal)
        for event, count, action in (
            ('desktop', 1, lambda: self.command('gaming')),
            ('gaming', 1, lambda: (self.root / 'stop-gaming').touch()),
            ('desktop', 2, None),
        ):
            self.wait_event(event, count)
            mode, group, ttou_ignored = self.sessions()[-1]
            self.assertEqual((mode, ttou_ignored), (event, '0'))
            deadline = time.monotonic() + 5
            while os.tcgetpgrp(master) != int(group):
                self.assertLess(
                    time.monotonic(), deadline, f'{event} lacks the terminal'
                )
                time.sleep(0.03)
            if action:
                action()
        self.stop()
        self.assertEqual(len(self.sessions()), 3)

    def test_requests_need_a_supervisor_and_a_new_login_starts_desktop(self):
        self.assertEqual(
            json.loads(self.command('status').stdout),
            dict(available=False, gaming=False),
        )
        for mode in ('desktop', 'gaming'):
            result = self.command(mode, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('requires the TTY1 session supervisor', result.stderr)
        self.assertEqual(self.events(), [])
        self.state.mkdir()
        (self.state / 'next').write_text('gaming')
        self.start()
        self.wait_event('desktop')
        self.assertNotIn('gaming', self.events())
        self.assertFalse((self.state / 'next').exists())

    def test_failed_native_stop_still_ends_owned_session(self):
        self.env['SESSION_TEST_STOP_FAIL'] = '1'
        self.start()
        self.wait_event('desktop')
        self.command('gaming')
        self.wait_event('gaming')
        self.assertEqual(
            self.events()[:5],
            [
                'desktop',
                'stop-desktop',
                'stop-desktop-failed',
                'term-desktop',
                'gaming',
            ],
        )
        self.assertFalse((self.state / 'next').exists())
        with (
            patch.object(modes, 'gaming_available', return_value=False),
            self.assertRaises(ValueError),
        ):
            modes.request_mode(self.state, 'gaming')
        self.assertFalse((self.state / 'next').exists())

    def test_failed_preflight_keeps_the_desktop_running(self):
        self.start()
        self.wait_event('desktop')
        self.env['SESSION_TEST_CHECK_FAIL'] = '1'
        result = self.command('gaming', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No connected display', result.stderr)
        self.assertEqual(self.events(), ['desktop'])
        self.assertFalse((self.state / 'next').exists())

    def test_auto_gpu_follows_display_wiring_and_offloads_steam_separately(self):
        (self.drm / 'card0-DP-1/status').write_text('disconnected\n')
        self.drm_card('card1', '1002:1681', {'eDP-2': 'connected', 'DP-3': 'connected'})
        result = self.gaming(SYSTEM_GAMING_DRY_RUN='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--prefer-vk-device 1002:1681', result.stdout)
        self.assertIn('--prefer-output DP-3\\,eDP-2', result.stdout)
        self.assertIn(
            '-- switcherooctl launch steam -gamepadui -steamos3', result.stdout
        )
        self.assertFalse((self.runtime / 'gaming-session').exists())
        result = self.gaming('--check', SYSTEM_GAMING_GPU='1002:73df')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No connected display', result.stderr)

    def test_output_preferences_choose_and_filter_the_scanout_gpu(self):
        self.drm_card('card1', '1002:1681', {'eDP-2': 'connected', 'DP-3': 'connected'})
        result = self.gaming('--check', SYSTEM_GAMING_OUTPUT='eDP-2,DP-1,DP-3')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GPU 1002:1681; connected outputs eDP-2,DP-3', result.stdout)
        result = self.gaming(
            '--check', SYSTEM_GAMING_OUTPUT='DP-1,DP-3', SYSTEM_GAMING_GPU='1002:1681'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('connected outputs DP-3', result.stdout)
        result = self.gaming('--check', SYSTEM_GAMING_OUTPUT='HDMI-A-9')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No connected display', result.stderr)

    def test_gaming_command_preserves_hardware_settings_and_exports_steam_features(
        self,
    ):
        result = subprocess.run(
            [str(GAMING)],
            env=dict(
                self.env,
                SYSTEM_GAMING_DRY_RUN='1',
                SYSTEM_GAMING_GPU='1002:73df',
                SYSTEM_GAMING_HDR='1',
                SYSTEM_GAMING_OUTPUT='DP-1',
                SYSTEM_GAMING_USER_CONFIG='/nonexistent',
                SESSION_MODE_READY_FD='9',
            ),
            check=True,
            text=True,
            capture_output=True,
        )
        for part in (
            '--backend drm',
            '--steam',
            '--ready-fd /proc/self/fd/9',
            '--prefer-output DP-1',
            '--prefer-vk-device 1002:73df',
            '--hdr-enabled',
            '-gamepadui -steamos3',
            'STEAM_GAMESCOPE_HDR_SUPPORTED=1',
            'STEAM_MULTIPLE_XWAYLANDS=1',
            'STEAM_USE_MANGOAPP=1',
            f'MANGOHUD_CONFIGFILE={self.runtime}/gaming-session/mangohud.conf',
        ):
            self.assertIn(part, result.stdout)
        result = subprocess.run(
            [str(GAMING)],
            env=dict(
                self.env,
                SYSTEM_GAMING_DRY_RUN='1',
                SYSTEM_GAMING_HDR='0',
                SYSTEM_GAMING_USER_CONFIG='/nonexistent',
            ),
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertNotIn('HDR', result.stdout.replace('--hdr', ''))


@unittest.skipUnless(
    os.environ.get('GAMESCOPE_LIVE_TEST') == '1',
    'Set GAMESCOPE_LIVE_TEST=1 to check the installed Vulkan/Xwayland stack',
)
class NativeGamescopeTests(unittest.TestCase):
    def test_readiness_and_client_exit_reports_with_the_installed_compositor(self):
        binary = shutil.which('gamescope')
        self.assertIsNotNone(binary)
        read, write = os.pipe()
        # Same shape as gaming-session: the client reaches the pipe through the
        # compositor's descriptor because Gamescope closes it in children.
        launcher = (
            'exec "$0" --backend headless --xwayland-count 1 '
            '--ready-fd "/proc/self/fd/$1" -- sh -c "$2" client "/proc/$$/fd/$1"'
        )
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                ['sh', '-c', launcher, binary, str(write), 'echo exited > "$1"'],
                pass_fds=(write,),
                stdout=output,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                start_new_session=True,
            )
            os.close(write)
            lines = []
            try:
                deadline = time.monotonic() + 12
                while len(lines) < 2 and time.monotonic() < deadline:
                    if select.select([read], [], [], 1)[0]:
                        data = os.read(read, 4096)
                        if not data:
                            break
                        lines += data.decode().splitlines()
                self.assertTrue(lines, 'Gamescope never signaled readiness')
                payload = lines[0].split()
                self.assertEqual(
                    len(payload),
                    2,
                    f'Expected X11 and Wayland displays, got {payload!r}',
                )
                self.assertTrue(payload[0].startswith(':'))
                self.assertTrue(payload[1].startswith('gamescope-'))
                self.assertEqual(lines[1:], ['exited'], 'Client exit was not reported')
            finally:
                os.close(read)
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    unittest.main()
