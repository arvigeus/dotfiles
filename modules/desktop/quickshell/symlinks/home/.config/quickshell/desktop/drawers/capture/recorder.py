"""Socket-activated recording owner for the shell (desktop-capture.socket).

The service outlives QML reloads. Only it owns the recorder and its IPC socket;
no process-name matching or signals to recordings started by another program.
Clients send newline-JSON commands. Each command gets one state line marked
`reply`; unmarked lines report later changes. A slow reader is never dropped or
sent part of a line: it receives the newest state once it catches up. Without a
recording or client the service exits after a short idle period and systemd
starts it on demand again.
"""

import datetime
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import socket
import subprocess
import tempfile
import time

DEFAULTS = {'systemAudio': True, 'microphone': False, 'pointer': True}
IDLE_EXIT = 30
# Seconds until the first captured frame, and from SIGINT until the file is saved.
START_TIMEOUT = 20
STOP_TIMEOUT = 15
# Unsent replies beyond this mean a client sends commands without reading.
OUTPUT_LIMIT = 1 << 16


def config_dir():
    base = os.environ.get('XDG_CONFIG_HOME', '')
    return (
        Path(base) if os.path.isabs(base) else Path.home() / '.config'
    ) / 'quickshell/desktop'


def runtime_dir():
    return (
        Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
        / 'desktop-capture'
    )


def atomic_write(path, text):
    """Replace a file atomically (through symlinks), leaving no partial file behind."""
    path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def location(kind):
    result = subprocess.run(
        ['xdg-user-dir', kind.upper()], capture_output=True, text=True, check=True
    )
    return Path(result.stdout.strip() or str(Path.home() / kind.title()))


def recording_command(source, path, options, ipc):
    if not isinstance(source, str) or not re.fullmatch(
        r'[A-Za-z0-9_][\w.-]*|\d+x\d+\+-?\d+\+-?\d+', source
    ):
        raise ValueError('Choose a connected display or select a recording area.')
    command = [
        'gpu-screen-recorder',
        '-w',
        source,
        '-f',
        '60',
        '-k',
        'h264',
        '-ac',
        'aac',
        '-cursor',
        'yes' if options['pointer'] else 'no',
        '-write-first-frame-ts',
        'yes',
        '-o',
        str(path),
        '-ipc',
        str(ipc),
    ]
    audio = []
    if options['systemAudio']:
        audio.append('default_output')
    if options['microphone']:
        audio.append('default_input')
    if audio:
        command.extend(['-a', '|'.join(audio)])
    return command


def check_microphone():
    default = subprocess.run(
        ['pactl', 'get-default-source'],
        check=True,
        capture_output=True,
        text=True,
        timeout=3,
    ).stdout.strip()
    sources = json.loads(
        subprocess.run(
            ['pactl', '--format=json', 'list', 'sources'],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout
    )
    source = next((source for source in sources if source.get('name') == default), None)
    # PulseAudio may use a speaker monitor as its default input when no mic exists.
    if (
        not source
        or source.get('properties', {}).get('device.class') == 'monitor'
        or default.endswith('.monitor')
    ):
        raise ValueError(
            'No microphone is available. Connect one or turn off Microphone before recording.'
        )


class Recorder:
    def __init__(self):
        self.options = dict(DEFAULTS)
        self.preference = config_dir() / 'recording.json'
        try:
            saved = json.loads(self.preference.read_text())
            self.options.update(
                {
                    key: value
                    for key, value in saved.items()
                    if key in DEFAULTS and type(value) is bool
                }
            )
        except (OSError, ValueError, AttributeError):
            pass
        self.directory = runtime_dir()
        self.ipc = self.directory / 'recorder.sock'
        self.log_path = self.directory / 'recorder.log'
        self.process = None
        self.log = None
        self.phase = 'idle'
        self.path = ''
        self.last_video = ''
        self.error = ''
        self.elapsed = 0.0
        self.since = 0.0
        self.deadline = math.inf
        self.pictures = str(location('pictures') / 'Screenshots')
        self.videos = str(location('videos') / 'Recordings')

    def snapshot(self):
        elapsed = self.elapsed + (
            time.monotonic() - self.since if self.phase == 'recording' else 0
        )
        return dict(
            available=bool(shutil.which('gpu-screen-recorder')),
            phase=self.phase,
            options=self.options,
            elapsed=int(elapsed),
            path=self.path,
            lastVideo=self.last_video,
            error=self.error,
            pictures=self.pictures,
            videos=self.videos,
        )

    def request(self, request):
        operation = request.get('op')
        if operation == 'start':
            if self.process:
                raise ValueError('A recording is already running.')
            if not shutil.which('gpu-screen-recorder'):
                raise ValueError('Install gpu-screen-recorder to record your screen.')
            if self.options['microphone']:
                check_microphone()
            source = request.get('source', '')
            folder = Path(self.videos)
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
            path = folder / f'Recording_{stamp}.mp4'
            command = recording_command(source, path, self.options, self.ipc)
            self.ipc.unlink(missing_ok=True)
            self.log = self.log_path.open('w')
            try:
                self.process = subprocess.Popen(
                    command, stdout=self.log, stderr=self.log
                )
            except OSError:
                self.log.close()
                self.log = None
                raise
            self.path = str(path)
            self.phase = 'starting'
            self.deadline = time.monotonic() + START_TIMEOUT
            self.elapsed = 0
            self.error = ''
        elif operation == 'stop':
            if self.process and self.phase != 'stopping':
                # SIGINT is the recorder's documented save-and-exit operation.
                # It also works while GPU/IPC initialization is still underway.
                self.elapsed = self.snapshot()['elapsed']
                self.process.send_signal(signal.SIGINT)
                self.phase = 'stopping'
                self.deadline = time.monotonic() + STOP_TIMEOUT
        elif operation == 'pause':
            if self.phase not in ('recording', 'paused'):
                raise ValueError('The recorder is not ready to pause.')
            paused = self.phase == 'recording'
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(3)
                connection.connect(str(self.ipc))
                connection.sendall(
                    (
                        json.dumps(dict(id=1, name='set-paused', data=paused)) + '\n'
                    ).encode()
                )
                reply = json.loads(connection.makefile('r').readline())
            if reply.get('result') != 'ok':
                raise ValueError(
                    str(reply.get('data', 'Could not pause the recording.'))
                )
            if paused:
                self.elapsed += time.monotonic() - self.since
            else:
                self.since = time.monotonic()
            self.phase = 'paused' if paused else 'recording'
        elif operation == 'option':
            if self.process:
                raise ValueError('Stop recording before changing recording options.')
            key, value = request.get('key'), request.get('value')
            if key not in DEFAULTS or type(value) is not bool:
                raise ValueError('Unknown recording option.')
            options = dict(self.options, **{key: value})
            atomic_write(self.preference, json.dumps(options) + '\n')
            self.options = options
        elif operation == 'clear-error':
            self.error = ''
        elif operation != 'status':
            raise ValueError('Unknown recording command.')

    def tick(self):
        if not self.process:
            return
        code = self.process.poll()
        if code is not None:
            self.log.close()
            self.log = None
            self.process = None
            if (
                code == 0
                and Path(self.path).is_file()
                and Path(self.path).stat().st_size
            ):
                self.last_video = self.path
            else:
                detail = self.log_path.read_text(errors='replace')[-2500:]
                self.error = 'Recording failed. ' + (
                    detail.strip() or f'Recorder exited with status {code}.'
                )
            self.phase = 'idle'
            self.elapsed = 0
            Path(self.path + '.ts').unlink(missing_ok=True)
        elif self.phase == 'starting':
            # The IPC socket is created before GPU initialization. The timestamp
            # sidecar is published only once frames are actually being captured.
            timestamp = Path(self.path + '.ts')
            if timestamp.exists() and timestamp.stat().st_size:
                self.phase = 'recording'
                self.since = time.monotonic()
                self.deadline = math.inf
                timestamp.unlink()
            elif time.monotonic() > self.deadline:
                self.note('The recorder took too long to start.')
                self.request({'op': 'stop'})
        elif self.phase == 'stopping' and time.monotonic() > self.deadline:
            # A recorder that ignores SIGINT would otherwise keep the service
            # busy forever. Its unfinished file is left in place.
            self.note(
                f'The recorder did not stop within {STOP_TIMEOUT} seconds and was killed.'
            )
            self.process.kill()
            self.deadline = math.inf

    def note(self, message):
        """Add a service diagnosis to the log that failure messages quote."""
        self.log.write(f'\n{message}\n')
        self.log.flush()

    def close(self):
        if self.process:
            self.request({'op': 'stop'})
            try:
                self.process.wait(timeout=STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.tick()


class Client:
    """A control connection: unparsed commands, unsent lines and the last state queued."""

    def __init__(self, state):
        self.input = bytearray()
        self.output = bytearray()
        self.state = state


def listener(endpoint):
    """The socket systemd passed in (LISTEN_FDS), or a private one for manual runs."""
    if (
        os.environ.get('LISTEN_PID') == str(os.getpid())
        and os.environ.get('LISTEN_FDS') == '1'
    ):
        for key in ('LISTEN_PID', 'LISTEN_FDS', 'LISTEN_FDNAMES'):
            os.environ.pop(key, None)
        return socket.socket(fileno=3), False
    endpoint.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    endpoint.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(endpoint))
    os.chmod(endpoint, 0o600)
    server.listen()
    return server, True


def serve():
    endpoint = runtime_dir() / 'control.sock'
    server, owned = listener(endpoint)
    server.setblocking(False)
    recorder = Recorder()
    selector = selectors.DefaultSelector()
    selector.register(server, selectors.EVENT_READ)
    wake, writer = socket.socketpair()
    writer.setblocking(False)
    signal.set_wakeup_fd(writer.fileno())
    selector.register(wake, selectors.EVENT_READ)
    stopping = False

    def terminate(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    clients = {}

    def disconnect(connection):
        selector.unregister(connection)
        clients.pop(connection)
        connection.close()

    def flush(connection):
        client = clients[connection]
        try:
            del client.output[: connection.send(client.output)]
        except BlockingIOError:
            pass
        except OSError:
            disconnect(connection)
            return
        if len(client.output) > OUTPUT_LIMIT:
            disconnect(connection)
            return
        events = selectors.EVENT_READ | (selectors.EVENT_WRITE if client.output else 0)
        if selector.get_key(connection).events != events:
            selector.modify(connection, events)

    def queue(connection, snapshot, reply=False):
        client = clients[connection]
        client.state = json.dumps(snapshot)
        line = json.dumps(dict(snapshot, reply=True)) if reply else client.state
        client.output += line.encode() + b'\n'
        flush(connection)

    def receive(connection):
        try:
            data = connection.recv(8192)
        except BlockingIOError:
            return
        except OSError:
            data = b''
        buffer = clients[connection].input
        buffer.extend(data)
        while b'\n' in buffer:
            line, _, rest = buffer.partition(b'\n')
            buffer[:] = rest
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('Expected a recording command object.')
                recorder.request(request)
            except (
                ValueError,
                OSError,
                TypeError,
                subprocess.SubprocessError,
            ) as error:
                recorder.error = str(error)
            queue(connection, recorder.snapshot(), reply=True)
            if connection not in clients:
                return
        if not data or len(buffer) > 8192:
            disconnect(connection)

    idle_since = time.monotonic()
    try:
        while not stopping:
            if recorder.process or clients:
                idle_since = time.monotonic()
            elif not owned and time.monotonic() - idle_since >= IDLE_EXIT:
                # Queued connections stay in systemd's socket and restart the service.
                break
            timeout = (
                0.25 if recorder.process else None if owned or clients else IDLE_EXIT
            )
            for key, events in selector.select(timeout):
                connection = key.fileobj
                if connection is wake:
                    wake.recv(1024)
                elif connection is server:
                    try:
                        client, _ = server.accept()
                    except BlockingIOError:
                        continue
                    client.setblocking(False)
                    clients[client] = Client(json.dumps(recorder.snapshot()))
                    selector.register(client, selectors.EVENT_READ)
                else:
                    if events & selectors.EVENT_WRITE and connection in clients:
                        flush(connection)
                    if events & selectors.EVENT_READ and connection in clients:
                        receive(connection)
            recorder.tick()
            snapshot = recorder.snapshot()
            state = json.dumps(snapshot)
            for connection, client in list(clients.items()):
                # A backlogged reader gets only the newest state once it drains.
                if client.state != state and not client.output:
                    queue(connection, snapshot)
    finally:
        recorder.close()
        for connection in list(clients):
            disconnect(connection)
        if owned:
            endpoint.unlink(missing_ok=True)
        signal.set_wakeup_fd(-1)
        selector.close()
        server.close()
        wake.close()
        writer.close()


if __name__ == '__main__':
    serve()
