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


class MoviesWorkerTests(unittest.TestCase):
    def test_close_stops_owned_child_and_preserves_detached_application(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'cleanup'
            body = """import json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from spaces.movies.worker import own_process_group
own_process_group(lambda:Path(sys.argv[2]).write_text('cleaned'))
child=subprocess.Popen(['sleep','30'])
app=subprocess.Popen(['sleep','30'],start_new_session=True)
print(json.dumps([child.pid,app.pid]),flush=True)
time.sleep(30)
"""
            process = subprocess.Popen(
                [sys.executable, '-u', '-c', body, str(support.DESKTOP), str(marker)],
                stdout=subprocess.PIPE,
                text=True,
            )
            child, app = json.loads(process.stdout.readline())
            try:
                process.terminate()
                process.wait(timeout=4)
                self.assertEqual(marker.read_text(), 'cleaned')
                status = Path(f'/proc/{child}/stat')
                self.assertTrue(
                    not status.exists() or status.read_text().split()[2] == 'Z'
                )
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
