"""Recording ownership, audio routing and native IPC without host capture."""

import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import support

BACKEND = support.DESKTOP / 'drawers/capture/recorder.py'
recorder = support.load('capture_recorder', BACKEND)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.environment = patch.dict(
            os.environ,
            XDG_CONFIG_HOME=str(self.root / 'config'),
            XDG_RUNTIME_DIR=str(self.root),
        )
        self.environment.start()
        self.location = patch.object(
            recorder, 'location', side_effect=lambda kind: self.root / kind
        )
        self.location.start()
        self.root.joinpath('desktop-capture').mkdir()

    def tearDown(self):
        self.location.stop()
        self.environment.stop()
        self.directory.cleanup()

    def test_sources_are_literal_and_audio_is_one_mixed_track(self):
        for audio, microphone, expected in (
            (True, True, 'default_output|default_input'),
            (True, False, 'default_output'),
            (False, True, 'default_input'),
            (False, False, None),
        ):
            command = recorder.recording_command(
                '1920x1080+-100+0',
                '/tmp/video with spaces.mp4',
                dict(systemAudio=audio, microphone=microphone, pointer=False),
                '/tmp/ipc',
            )
            self.assertIn('/tmp/video with spaces.mp4', command)
            self.assertEqual(command[command.index('-cursor') + 1], 'no')
            if expected:
                self.assertEqual(command[command.index('-a') + 1], expected)
                self.assertEqual(command.count('-a'), 1)
            else:
                self.assertNotIn('-a', command)
        for source in ('', '-o', 'DP-1|/dev/video0', '$(touch /tmp/unsafe)', None):
            with self.subTest(source=source), self.assertRaises(ValueError):
                recorder.recording_command(
                    source, '/tmp/test.mp4', recorder.DEFAULTS, '/tmp/ipc'
                )

    def test_options_are_saved_and_reloaded_with_boolean_validation(self):
        owner = recorder.Recorder()
        owner.request(dict(op='option', key='microphone', value=True))
        self.assertTrue(recorder.Recorder().options['microphone'])
        for request in (
            dict(op='option', key='unknown', value=True),
            dict(op='option', key='pointer', value='false'),
        ):
            with self.assertRaises(ValueError):
                owner.request(request)
        self.assertTrue(owner.options['pointer'])

    def test_missing_microphone_never_records_a_speaker_monitor_as_input(self):
        owner = recorder.Recorder()
        owner.options['microphone'] = True
        results = [
            MagicMock(stdout='speakers.monitor\n'),
            MagicMock(
                stdout=json.dumps(
                    [
                        dict(
                            name='speakers.monitor',
                            properties={'device.class': 'monitor'},
                        )
                    ]
                )
            ),
        ]
        with (
            patch.object(recorder.subprocess, 'run', side_effect=results),
            patch.object(recorder.subprocess, 'Popen') as launch,
        ):
            with self.assertRaisesRegex(ValueError, 'No microphone'):
                owner.request(dict(op='start', source='DP-3'))
            launch.assert_not_called()

    def test_duplicate_start_stop_saving_and_completion(self):
        owner = recorder.Recorder()
        process = MagicMock()
        process.poll.return_value = None
        with (
            patch.object(
                recorder.shutil, 'which', return_value='/usr/bin/gpu-screen-recorder'
            ),
            patch.object(recorder.subprocess, 'Popen', return_value=process),
        ):
            owner.request(dict(op='start', source='DP-3'))
            with self.assertRaisesRegex(ValueError, 'already running'):
                owner.request(dict(op='start', source='DP-3'))
            with self.assertRaisesRegex(ValueError, 'Stop recording'):
                owner.request(dict(op='option', key='pointer', value=False))
            owner.ipc.touch()
            owner.tick()
            self.assertEqual(owner.phase, 'starting')
            Path(owner.path + '.ts').write_text('first frame')
            owner.tick()
            self.assertEqual(owner.phase, 'recording')
            owner.request(dict(op='stop'))
            owner.request(dict(op='stop'))
            process.send_signal.assert_called_once_with(signal.SIGINT)
            self.assertEqual(owner.phase, 'stopping')
            self.assertEqual(owner.last_video, '')
            Path(owner.path).write_bytes(b'saved video')
            process.poll.return_value = 0
            owner.tick()
            self.assertEqual(owner.phase, 'idle')
            self.assertEqual(owner.last_video, owner.path)
            self.assertFalse(owner.error)

    def test_pause_and_resume_acknowledgement_freeze_elapsed(self):
        owner = recorder.Recorder()
        owner.phase = 'recording'
        owner.since = 10
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.makefile.return_value = io.StringIO('{"id":1,"result":"ok"}\n')
        with (
            patch.object(recorder.socket, 'socket', return_value=connection),
            patch.object(recorder.time, 'monotonic', return_value=13.5),
        ):
            owner.request(dict(op='pause'))
            self.assertEqual(owner.phase, 'paused')
            self.assertEqual(owner.snapshot()['elapsed'], 3)
            request = json.loads(connection.sendall.call_args.args[0])
            self.assertEqual(request, dict(id=1, name='set-paused', data=True))
        connection.makefile.return_value = io.StringIO('{"id":1,"result":"ok"}\n')
        with (
            patch.object(recorder.socket, 'socket', return_value=connection),
            patch.object(recorder.time, 'monotonic', return_value=100),
        ):
            owner.request(dict(op='pause'))
        with patch.object(recorder.time, 'monotonic', return_value=102):
            self.assertEqual(owner.snapshot()['elapsed'], 5)

    def test_unresponsive_recorder_is_killed_and_frees_the_service(self):
        owner = recorder.Recorder()
        process = MagicMock()
        process.poll.return_value = None
        clock = MagicMock(return_value=100.0)
        with (
            patch.object(
                recorder.shutil, 'which', return_value='/usr/bin/gpu-screen-recorder'
            ),
            patch.object(recorder.subprocess, 'Popen', return_value=process),
            patch.object(recorder.time, 'monotonic', clock),
        ):
            owner.request(dict(op='start', source='DP-3'))
            clock.return_value += recorder.START_TIMEOUT - 1
            owner.tick()
            self.assertEqual(owner.phase, 'starting')
            # No first frame: the start watchdog asks the recorder to save and exit.
            clock.return_value += 2
            owner.tick()
            process.send_signal.assert_called_once_with(signal.SIGINT)
            self.assertEqual(owner.phase, 'stopping')
            clock.return_value += recorder.STOP_TIMEOUT - 1
            owner.tick()
            process.kill.assert_not_called()
            # It ignored SIGINT: kill once instead of staying busy forever.
            clock.return_value += 2
            owner.tick()
            owner.tick()
            process.kill.assert_called_once_with()
            self.assertEqual(owner.phase, 'stopping')
            process.poll.return_value = -signal.SIGKILL
            owner.tick()
            self.assertEqual(owner.phase, 'idle')
            self.assertIn('took too long to start', owner.error)
            self.assertIn('did not stop within', owner.error)
            self.assertFalse(owner.last_video)

            # A started recording that hangs while saving is reported the same way.
            replacement = MagicMock()
            replacement.poll.return_value = None
            recorder.subprocess.Popen.return_value = replacement
            owner.request(dict(op='start', source='DP-3'))
            Path(owner.path + '.ts').write_text('first frame')
            owner.tick()
            self.assertEqual(owner.phase, 'recording')
            clock.return_value += 3600
            owner.tick()
            replacement.kill.assert_not_called()
            owner.request(dict(op='stop'))
            clock.return_value += recorder.STOP_TIMEOUT + 1
            owner.tick()
            replacement.kill.assert_called_once_with()
            replacement.poll.return_value = -signal.SIGKILL
            owner.tick()
            self.assertEqual(owner.phase, 'idle')
            self.assertNotIn('took too long to start', owner.error)
            self.assertIn('did not stop within', owner.error)

    def test_failed_start_reports_log_and_never_announces_saved_file(self):
        owner = recorder.Recorder()
        process = MagicMock()
        process.poll.return_value = 1
        with patch.object(recorder.subprocess, 'Popen', return_value=process):
            owner.request(dict(op='start', source='DP-3'))
        owner.log.write('encoder unavailable')
        owner.log.flush()
        owner.tick()
        self.assertEqual(owner.phase, 'idle')
        self.assertIn('encoder unavailable', owner.error)
        self.assertFalse(owner.last_video)

    def test_service_reconnect_pause_stop_and_shutdown_finalize(self):
        """A fresh shell client reconnects to the same recording owner."""
        binary = self.root / 'bin'
        binary.mkdir()
        userdir = binary / 'xdg-user-dir'
        userdir.write_text(
            '#!/usr/bin/env python3\nimport os,sys\nprint(os.environ["XDG_RUNTIME_DIR"]+"/"+sys.argv[1])\n'
        )
        userdir.chmod(0o755)
        native = binary / 'gpu-screen-recorder'
        native.write_text("""#!/usr/bin/env python3
import json,os,signal,socket,sys
args=sys.argv
ipc=args[args.index('-ipc')+1]
path=args[args.index('-o')+1]
def stop(*_):
    open(path,'wb').write(b'finalized')
    sys.exit(0)
signal.signal(signal.SIGINT,stop)
server=socket.socket(socket.AF_UNIX);server.bind(ipc);server.listen()
open(path+'.ts','w').write('first frame')
while True:
    client,_=server.accept()
    request=json.loads(client.makefile().readline())
    client.sendall((json.dumps(dict(id=request['id'],result='ok'))+'\\n').encode())
    client.close()
""")
        native.chmod(0o755)
        env = dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'])
        process = subprocess.Popen(
            ['python3', '-B', str(BACKEND)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        endpoint = recorder.runtime_dir() / 'control.sock'
        deadline = time.monotonic() + 4
        while (
            not endpoint.exists()
            and process.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)

        def connect(request):
            connection = socket.socket(socket.AF_UNIX)
            connection.settimeout(4)
            connection.connect(str(endpoint))
            connection.sendall((json.dumps(request) + '\n').encode())
            return connection

        def command(request):
            with connect(request) as connection:
                return json.loads(connection.makefile().readline())

        def state_until(predicate):
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                with connect(dict(op='status')) as connection:
                    state = json.loads(connection.makefile().readline())
                if predicate(state):
                    return state
                time.sleep(0.03)
            self.fail('State did not settle: ' + str(state))

        try:
            self.assertTrue(command(dict(op='start', source='DP-3'))['available'])
            first = state_until(lambda state: state['phase'] == 'recording')
            # A status client may close before reading any reply (shell reload).
            for _ in range(20):
                connect(dict(op='status')).close()
            self.assertEqual(command(dict(op='status'))['error'], '')
            self.assertEqual(command(dict(op='pause'))['phase'], 'paused')
            # The watch that started this session is gone; a new client sees it paused.
            reconnected = command(dict(op='status'))
            self.assertEqual(reconnected['phase'], 'paused')
            self.assertEqual(reconnected['path'], first['path'])
            command(dict(op='pause'))
            command(dict(op='stop'))
            saved = state_until(lambda state: state['phase'] == 'idle')
            self.assertEqual(Path(saved['lastVideo']).read_bytes(), b'finalized')
            self.assertEqual(saved['error'], '')
            command(dict(op='start', source='DP-3'))
            running = state_until(lambda state: state['phase'] == 'recording')
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertEqual(Path(running['path']).read_bytes(), b'finalized')
            self.assertFalse(endpoint.exists())
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)

    def activate(self, *requests, idle_exit=30):
        """Start the service on an inherited listener, as desktop-capture.socket does.

        Each request is sent from its own client before the service starts.
        """
        endpoint = self.root / 'desktop-capture/control.sock'
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(endpoint))
        listener.listen()
        self.addCleanup(listener.close)
        clients = []
        for request in requests:
            client = socket.socket(socket.AF_UNIX)
            client.settimeout(4)
            client.connect(str(endpoint))
            client.sendall(request)
            self.addCleanup(client.close)
            clients.append(client)
        script = (
            'import os,runpy,sys\nos.dup2(int(sys.argv[2]),3)\nos.environ["LISTEN_PID"]=str(os.getpid())\n'
            'os.environ["LISTEN_FDS"]="1"\nimport importlib.util\n'
            'spec=importlib.util.spec_from_file_location("r",sys.argv[1]);r=importlib.util.module_from_spec(spec)\n'
            f'spec.loader.exec_module(r);r.IDLE_EXIT={idle_exit};'
            'r.location=lambda kind:r.Path(os.environ["XDG_RUNTIME_DIR"])/kind\n'
            'r.serve()\n'
        )
        process = subprocess.Popen(
            [sys.executable, '-B', '-c', script, str(BACKEND), str(listener.fileno())],
            pass_fds=(listener.fileno(),),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def stop():
            if process.poll() is None:
                process.kill()
                process.communicate()

        self.addCleanup(stop)
        return endpoint, process, clients

    def test_socket_activation_uses_inherited_listener_and_exits_when_idle(self):
        endpoint, process, (client,) = self.activate(
            b'{"op":"status"}\n{"op":"option","key":"pointer","value":false}\n',
            idle_exit=0.3,
        )
        with client, client.makefile() as replies:
            status, option = (json.loads(replies.readline()) for _ in range(2))
        # One tagged reply per command; the requester is not sent its state again.
        self.assertEqual((status['reply'], status['phase']), (True, 'idle'))
        self.assertEqual((option['reply'], option['options']['pointer']), (True, False))
        # No client and no recording: the service exits; systemd keeps the socket.
        _, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertTrue(endpoint.exists())

    def test_slow_reader_keeps_its_session_and_gets_the_newest_state(self):
        _, process, (stalled, editor) = self.activate(
            b'{"op":"status"}\n', b'{"op":"status"}\n'
        )
        with editor.makefile() as replies:
            self.assertTrue(json.loads(replies.readline())['reply'])
            # Far more changes than a socket buffer holds while one shell is stalled.
            for change in range(1500):
                value = bool(change % 2)
                editor.sendall(
                    json.dumps(dict(op='option', key='pointer', value=value)).encode()
                    + b'\n'
                )
                reply = json.loads(replies.readline())
                while not reply.get('reply'):
                    reply = json.loads(replies.readline())
                self.assertIs(reply['options']['pointer'], value)
        lines = []
        with stalled.makefile() as updates:
            while not lines or lines[-1]['options']['pointer'] is not value:
                line = updates.readline()
                self.assertTrue(line.endswith('\n'), 'connection dropped: ' + line)
                lines.append(json.loads(line))
            self.assertTrue(lines[0]['reply'])
            self.assertLess(len(lines), 1500, 'changes were not coalesced')
            # The stalled shell still owns a working connection.
            stalled.sendall(b'{"op":"status"}\n')
            reply = json.loads(updates.readline())
            while not reply.get('reply'):
                reply = json.loads(updates.readline())
            self.assertIs(reply['options']['pointer'], value)
        self.assertIsNone(process.poll(), process.stderr)


if __name__ == '__main__':
    unittest.main()
