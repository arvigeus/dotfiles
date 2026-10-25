"""Explicit close releases worker-owned subprocesses and runs cleanup."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

import support


class PicturesWorkerTests(unittest.TestCase):
    def test_close_stops_owned_child_and_preserves_detached_application(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'cleanup'
            body = '''import json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from spaces.pictures.providers import install_shutdown_handler
install_shutdown_handler(lambda:Path(sys.argv[2]).write_text('cleaned'))
child=subprocess.Popen(['sleep','30'])
app=subprocess.Popen(['sleep','30'],start_new_session=True)
print(json.dumps([child.pid,app.pid]),flush=True)
time.sleep(30)
'''
            process = subprocess.Popen([sys.executable, '-u', '-c', body, str(support.DESKTOP), str(marker)], stdout=subprocess.PIPE, text=True)
            child, app = json.loads(process.stdout.readline())
            try:
                process.terminate()
                process.wait(timeout=4)
                self.assertEqual(marker.read_text(), 'cleaned')
                status = Path(f'/proc/{child}/stat')
                self.assertTrue(not status.exists() or status.read_text().split()[2] == 'Z')
                os.kill(app, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdout.close()
                for pid in (child, app):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_production_worker_protocol_uses_private_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run([sys.executable, str(support.DESKTOP / 'spaces/pictures/backend.py')],
                input=json.dumps({'id':1,'op':'preferences'})+'\n', capture_output=True, text=True, timeout=5,
                env={**os.environ, 'XDG_CONFIG_HOME':str(root/'config'), 'XDG_DATA_HOME':str(root/'data'),
                     'XDG_CACHE_HOME':str(root/'cache'), 'XDG_RUNTIME_DIR':str(root/'runtime'),
                     'PYTHONDONTWRITEBYTECODE':'1'})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'id':1,'result':{}})
