"""Exercise the real session supervisor with isolated compositor/client executables."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
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
        self.binary = self.root / 'bin'; self.binary.mkdir()
        self.runtime = self.root / 'runtime'; self.runtime.mkdir(mode=0o700)
        runner = self.binary / 'session-mode'
        runner.write_text(f'''#!/usr/bin/env python3
import functools,importlib.machinery,importlib.util,os,sys
from pathlib import Path
loader=importlib.machinery.SourceFileLoader('modes',{str(SOURCE)!r})
spec=importlib.util.spec_from_loader(loader.name,loader)
m=importlib.util.module_from_spec(spec);loader.exec_module(m)
m.runtime_directory=lambda:Path(os.environ['SESSION_TEST_RUNTIME'])
m.Supervisor=functools.partial(m.Supervisor,startup_timeout=.4,stop_timeout=.5)
sys.exit(m.main())
''')
        runner.chmod(0o755)
        stub = self.binary / 'fixture'
        stub.write_text('''#!/usr/bin/env python3
import os,sys,time
from pathlib import Path
root=Path(os.environ['SESSION_TEST_ROOT']);name=Path(sys.argv[0]).name

def log(text):
 with (root/'events').open('a') as output:output.write(text+'\\n')
def wait_for_stop(mode):
 stop=root/('stop-'+mode)
 while not stop.exists():time.sleep(.02)
 stop.unlink()
if name=='loginctl':
 if sys.argv[1]=='show-session':print('User='+str(os.getuid())+'\\nTTY=tty1\\nRemote=no')
 elif sys.argv[1]=='list-sessions':
  import json
  print(json.dumps([dict(session='fixture',uid=os.getuid(),tty='tty1',**{'class':'user'})]))
 else:
  log('terminate-login')
  if os.environ.get('SESSION_TEST_DENY'):raise SystemExit(1)
elif name=='uwsm':
 if sys.argv[1]=='check':raise SystemExit(1)
 if sys.argv[1]=='start':
  log('desktop');wait_for_stop('desktop')
 elif sys.argv[1]=='stop':
  log('stop-desktop');(root/'stop-desktop').touch()
elif name=='gaming-session':
 log('gaming')
 scenario=os.environ.get('SESSION_TEST_GAME','ready')
 if scenario=='fail':raise SystemExit(42)
 if scenario!='hang':os.write(int(os.environ['SESSION_MODE_READY_FD']),b'ready\\n')
 wait_for_stop('gaming')
elif name=='steam':
 assert sys.argv[1:]==['-shutdown'],sys.argv
 log('stop-gaming');(root/'stop-gaming').touch()
''')
        stub.chmod(0o755)
        for name in ('uwsm', 'gaming-session', 'steam', 'gamescope', 'loginctl'):
            (self.binary / name).symlink_to(stub)
        self.env = dict(os.environ, PATH=str(self.binary)+':'+os.environ['PATH'],
                        SESSION_TEST_ROOT=str(self.root), SESSION_TEST_RUNTIME=str(self.runtime),
                        XDG_SESSION_ID='fixture', PYTHONDONTWRITEBYTECODE='1')
        self.process = None
        self.addCleanup(self.stop)

    def command(self, *args, check=True):
        return subprocess.run([str(self.binary / 'session-mode'), *args], env=self.env,
                              check=check, text=True, capture_output=True, timeout=5)

    def start(self):
        self.process = subprocess.Popen([str(self.binary / 'session-mode'), 'run'], env=self.env,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.output = self.process.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.output = self.process.communicate()
                self.fail('Session owner did not terminate its fixture child')
            self.process = None

    def events(self):
        return (self.root / 'events').read_text().splitlines() if (self.root / 'events').exists() else []

    def wait_event(self, event, count=1):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            if self.events().count(event)>=count:return
            if self.process and self.process.poll() is not None:
                out, err = self.process.communicate()
                self.fail(f'Owner exited: {out} {err}')
            time.sleep(.03)
        self.fail(f'Missing {event} #{count}: {self.events()}')

    def test_desktop_gaming_return_hook_and_desktop_reload(self):
        self.start(); self.wait_event('desktop')
        self.assertTrue(json.loads(self.command('status').stdout)['supervised'])
        self.command('gaming'); self.wait_event('gaming')
        subprocess.run([str(HOOK), 'plasma'], env=self.env, check=True, timeout=5)
        self.wait_event('desktop', 2)
        self.command('desktop'); self.wait_event('desktop', 3)
        self.assertEqual(self.events()[:7], ['desktop', 'stop-desktop', 'gaming', 'stop-gaming',
                                          'desktop', 'stop-desktop', 'desktop'])
        self.assertFalse((self.runtime/'next.json').exists())

    def test_steam_exit_and_failed_gaming_start_return_to_desktop(self):
        for scenario in ('ready', 'fail'):
            with self.subTest(scenario=scenario):
                self.env['SESSION_TEST_GAME'] = scenario
                desktop_count = self.events().count('desktop')
                gaming_count = self.events().count('gaming')
                self.start(); self.wait_event('desktop', desktop_count+1)
                self.command('gaming'); self.wait_event('gaming', gaming_count+1)
                if scenario=='ready':(self.root/'stop-gaming').touch()
                self.wait_event('desktop', desktop_count+2)
                self.stop()

    def test_hung_gaming_start_times_out_to_desktop(self):
        self.env['SESSION_TEST_GAME']='hang'
        self.start(); self.wait_event('desktop')
        self.command('gaming'); self.wait_event('gaming')
        self.wait_event('desktop', 2)
        self.stop()
        self.assertIn('Gaming startup timed out', self.output[1])

    def test_live_console_handoff_is_consumed_once_and_next_login_is_desktop(self):
        self.command('gaming')
        self.assertIn('terminate-login', self.events())
        self.assertTrue((self.runtime/'handoff.json').exists())
        self.start(); self.wait_event('gaming')
        self.assertFalse((self.runtime/'handoff.json').exists())
        self.stop()
        self.start(); self.wait_event('desktop')
        self.assertEqual(self.events().count('gaming'), 1)

    def test_rejected_handoff_leaves_no_boot_choice(self):
        self.env['SESSION_TEST_DENY']='1'
        self.assertNotEqual(self.command('gaming', check=False).returncode, 0)
        self.assertFalse((self.runtime/'handoff.json').exists())

    def test_desktop_app_without_session_id_resolves_local_login(self):
        self.env.pop('XDG_SESSION_ID', None)
        state=json.loads(self.command('status').stdout)
        self.assertTrue(state['available'])
        self.assertTrue(state['gaming'])
        self.command('desktop')
        self.assertIn('terminate-login', self.events())

    def test_stale_requests_and_unavailable_gaming_are_rejected(self):
        modes.atomic_json(self.runtime/'handoff.json', dict(mode='gaming', created=time.monotonic()-120))
        self.assertIsNone(modes.take_request(self.runtime, 'handoff.json'))
        self.assertFalse((self.runtime/'handoff.json').exists())
        with patch.object(modes, 'gaming_available', return_value=False), self.assertRaises(ValueError):
            modes.request_mode(self.runtime, 'gaming')
        self.assertFalse((self.runtime/'handoff.json').exists())

    def test_gaming_command_preserves_hardware_settings_and_adds_steam_hook_mode(self):
        result = subprocess.run([str(GAMING)], env=dict(self.env, SYSTEM_GAMING_DRY_RUN='1',
            SYSTEM_GAMING_GPU='1002:73df', SYSTEM_GAMING_HDR='1', SYSTEM_GAMING_OUTPUT='DP-1',
            SESSION_MODE_READY_FD='9'), check=True, text=True, capture_output=True)
        for part in ('--backend drm', '--steam', '--ready-fd 9', '--prefer-output DP-1',
                     '--prefer-vk-device 1002:73df', '--hdr-enabled', '-gamepadui -steamos3'):
            self.assertIn(part, result.stdout)


if __name__=='__main__':unittest.main()
