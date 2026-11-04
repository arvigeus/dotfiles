"""Explicit close releases worker-owned subprocesses and runs cleanup."""

import json
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.movies.worker import serve


class MoviesWorkerTests(unittest.TestCase):
    def test_enrichment_leaves_foreground_scans_and_controls_available(self):
        entered = threading.Semaphore(0)
        release, foreground, scan, control = (threading.Event() for _ in range(4))
        output = io.StringIO()

        def handle(request):
            op = request['op']
            if op in ('content_rating', 'library_metadata'):
                entered.release()
                release.wait(3)
            else:
                dict(details=foreground, library_games=scan, set_favorite=control)[
                    op
                ].set()
            return op

        requests = io.StringIO(
            ''.join(
                json.dumps(dict(id=index, op=op)) + '\n'
                for index, op in enumerate(
                    (
                        'content_rating',
                        'library_metadata',
                        'details',
                        'library_games',
                        'set_favorite',
                    )
                )
            )
        )
        worker = threading.Thread(
            target=lambda: serve(
                handle,
                workers=1,
                enrichment=('content_rating', 'library_metadata'),
                background=('library_games',),
                controls=('set_favorite',),
                stream=requests,
                output=output,
            )
        )
        worker.start()
        try:
            self.assertTrue(entered.acquire(timeout=1))
            self.assertTrue(entered.acquire(timeout=1))
            self.assertTrue(foreground.wait(1))
            self.assertTrue(scan.wait(1))
            self.assertTrue(control.wait(1))
        finally:
            release.set()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(output.getvalue().splitlines()), 5)

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
