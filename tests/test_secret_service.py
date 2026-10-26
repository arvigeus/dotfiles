"""Real credential persistence and unattended unlock on an isolated session bus."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / 'modules/system/security/secret-service/files/usr/local/libexec/secret-service-unlock'


def exercise():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime = root / 'runtime'
        runtime.mkdir(mode=0o700)
        os.environ.update(HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_DATA_HOME=str(root / 'data'), XDG_RUNTIME_DIR=str(runtime))
        os.environ.pop('DISPLAY', None)
        os.environ.pop('WAYLAND_DISPLAY', None)
        key = root / 'config/secret-service/unlock-key'
        store = root / 'data/keyrings/login.keyring'
        helper = [sys.executable, '-c', f'import runpy; runpy.run_path({str(HELPER)!r})["main"]()']

        def run(*args, input=None, check=True):
            result = subprocess.run(args, input=input, text=True, capture_output=True, timeout=25)
            if check and result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            return result

        def start():
            daemon = subprocess.Popen([sys.executable, str(HELPER), '--daemon'],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 5
            while not (runtime / 'keyring/control').exists():
                if daemon.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Isolated keyring daemon did not start')
                time.sleep(0.02)
            run('gdbus', 'wait', '--session', '--timeout', '5', 'org.freedesktop.secrets')
            return daemon

        daemon = start()
        try:
            result = run(*helper)
            assert 'unlocked' in result.stdout
            original_key = key.read_bytes()
            assert key.stat().st_mode & 0o777 == 0o600
            run('secret-tool', 'store', '--label=Fixture', 'dotfiles-test', 'persistence', input='synthetic-only')
            assert store.exists() and b'synthetic-only' not in store.read_bytes()
            daemon.terminate()
            daemon.wait(timeout=5)
            daemon = start()
            run(*helper)
            assert key.read_bytes() == original_key
            assert run('secret-tool', 'lookup', 'dotfiles-test', 'persistence').stdout.strip() == 'synthetic-only'
            key.chmod(0o644)
            assert run(sys.executable, str(HELPER), check=False).returncode != 0
            key.chmod(0o600)
            key.unlink()
            before = store.read_bytes()
            assert run(sys.executable, str(HELPER), check=False).returncode != 0
            assert not key.exists() and store.read_bytes() == before
        finally:
            daemon.terminate()
            daemon.wait(timeout=5)


class SecretServiceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('gnome-keyring-daemon') and shutil.which('secret-tool'),
                         'GNOME Keyring and libsecret are required')
    def test_restart_preserves_credentials_without_a_password_prompt(self):
        result = subprocess.run(['dbus-run-session', '--', sys.executable, str(Path(__file__).resolve()), 'exercise'],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    if sys.argv[1:] == ['exercise']:
        exercise()
    else:
        unittest.main()
