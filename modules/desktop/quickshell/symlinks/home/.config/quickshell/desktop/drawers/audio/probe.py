"""Explicit speaker checks and an in-memory microphone recording/playback test."""

import io
import json
import math
import os
from pathlib import Path
import selectors
import signal
import struct
import subprocess
import sys
import time
import wave

import backend as audio


APPLICATION_ID = 'dotfiles.audio-test'
RATE = 24000
RECORD_SECONDS = 10
SAMPLES = Path('/usr/share/sounds/alsa')
VOICES = {
    'mono': 'Front_Center',
    'front-left': 'Front_Left',
    'front-right': 'Front_Right',
    'front-center': 'Front_Center',
    'rear-left': 'Rear_Left',
    'rear-right': 'Rear_Right',
    'rear-center': 'Rear_Center',
    'side-left': 'Side_Left',
    'side-right': 'Side_Right',
}


def report(phase, detail='', error=''):
    print(json.dumps(dict(phase=phase, detail=detail, error=error)), flush=True)


def connected(node):
    ports = audio.entries(node.get('ports'))
    return not ports or any(
        p['name'] == node.get('active_port') and audio.available(p.get('availability'))
        for p in ports
    )


def require_node(kind, name):
    node = next((n for n in audio.read(kind) if n['name'] == name), None)
    if (
        not node
        or not connected(node)
        or (kind == 'sources' and not audio.capture_source(node))
    ):
        raise ValueError('The test device is no longer available.')
    if node.get('mute'):
        raise ValueError('The test device is muted.')
    return node


def channel_audio(channel):
    sample = SAMPLES / (VOICES.get(channel, '') + '.wav')
    if channel in VOICES:
        if not sample.is_file():
            raise ValueError('Install alsa-utils to use the speaker test.')
        return sample.read_bytes()
    # ALSA has no spoken sample for LFE, height or auxiliary channels.
    frequency = 80 if channel == 'lfe' else 440
    count = int(RATE * 0.6)
    pcm = b''.join(
        struct.pack(
            '<h',
            int(
                6000
                * min(i / 240, (count - i) / 240, 1)
                * math.sin(2 * math.pi * frequency * i / RATE)
            ),
        )
        for i in range(count)
    )
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        wav.writeframes(pcm)
    return output.getvalue()


def client_args(device, stream):
    return [
        '--device=' + device,
        '--client-name=Audio test',
        '--stream-name=' + stream,
        '--property=application.id=' + APPLICATION_ID,
        '--property=node.dont-fallback=true',
        '--property=node.dont-reconnect=true',
        '--property=node.stream.restore-props=false',
        '--property=node.stream.restore-target=false',
    ]


class Probe:
    def __init__(self):
        self.cancelled = False
        self.released = False
        self.child = None
        self.terminating = False

    def cancel(self, *_):
        self.cancelled = True
        # Stop capture immediately even if an inventory query is still waiting.
        if self.child and self.child.poll() is None:
            try:
                self.terminating = True
                self.child.terminate()
            except ProcessLookupError:
                pass

    def check(self):
        if self.cancelled:
            raise InterruptedError

    def stop_child(self):
        if self.child is None:
            return
        child, terminating = self.child, self.terminating
        self.child, self.terminating = None, False
        if child.poll() is None:
            if not terminating:
                try:
                    child.terminate()
                except ProcessLookupError:
                    pass
            try:
                child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for stream in (child.stdin, child.stdout):
            if stream:
                stream.close()

    def play(self, device, data, *, channel=None, raw=False):
        self.check()
        require_node('sinks', device)
        args = ['paplay', *client_args(device, 'Audio test'), '--volume=65536']
        if channel:
            args += ['--channel-map=' + channel, '--no-remix']
        if raw:
            args += ['--raw', '--format=s16le', '--rate=' + str(RATE), '--channels=1']
        self.child = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 15
        first = True
        try:
            while True:
                self.check()
                if time.monotonic() >= deadline:
                    raise ValueError('Audio playback timed out.')
                try:
                    self.child.communicate(input=data if first else None, timeout=0.1)
                    if self.child.returncode:
                        raise ValueError(
                            'Could not play the audio test on this output.'
                        )
                    break
                except subprocess.TimeoutExpired:
                    first = False
                    require_node('sinks', device)
        finally:
            self.stop_child()

    def speakers(self):
        config, _ = audio.load_config()
        sinks = [n for n in audio.read('sinks') if not n.get('mute') and connected(n)]
        if not sinks:
            raise ValueError('No unmuted outputs are available.')
        for sink in sinks:
            channels = sink.get('channel_map', '')
            channels = (
                [name.strip() for name in channels.split(',') if name.strip()]
                if isinstance(channels, str)
                else channels
            )
            if not channels:
                raise ValueError('This output does not report its speaker channels.')
            for channel in channels:
                self.check()
                current = require_node('sinks', sink['name'])
                if current.get('active_port') != sink.get('active_port') or current.get(
                    'channel_map'
                ) != sink.get('channel_map'):
                    raise ValueError(
                        'The output connection changed. Run the test again.'
                    )
                port = next(
                    (
                        p
                        for p in audio.entries(current.get('ports'))
                        if p['name'] == current.get('active_port')
                    ),
                    {},
                )
                label = audio.describe(current, port, config)['label']
                report('speakers', label + ' · ' + channel.replace('-', ' ').title())
                data = channel_audio(channel)
                self.play(sink['name'], data, channel=channel)

    def record(self, source, detail=''):
        require_node('sources', source)
        self.child = subprocess.Popen(
            [
                'parec',
                *client_args(source, 'Microphone test'),
                '--raw',
                '--format=s16le',
                '--rate=' + str(RATE),
                '--channels=1',
                '--latency-msec=30',
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        data = bytearray()
        started = time.monotonic()
        last_check = started
        report('recording', detail)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(sys.stdin, selectors.EVENT_READ, 'control')
                selector.register(self.child.stdout, selectors.EVENT_READ, 'audio')
                while not self.released:
                    self.check()
                    now = time.monotonic()
                    if now - started >= 30:
                        raise ValueError('Microphone test timed out.')
                    if now - last_check >= 0.25:
                        require_node('sources', source)
                        last_check = now
                    if self.child and now - started >= RECORD_SECONDS:
                        selector.unregister(self.child.stdout)
                        self.stop_child()
                        report('ready', detail)
                    for key, _ in selector.select(timeout=0.05):
                        chunk = os.read(key.fd, 4096)
                        if key.data == 'control':
                            if not chunk:
                                raise InterruptedError
                            self.released = b'\n' in chunk
                        elif not chunk:
                            raise ValueError(
                                'Microphone recording stopped unexpectedly.'
                            )
                        else:
                            remaining = RECORD_SECONDS * RATE * 2 - len(data)
                            data.extend(chunk[:remaining])
        finally:
            self.stop_child()
        return data[: len(data) // 2 * 2]

    def microphone(self):
        info = json.loads(audio.command('-f', 'json', 'info'))
        source, sink = info.get('default_source_name'), info.get('default_sink_name')
        if not source or not sink:
            raise ValueError('Choose a default microphone and output first.')
        nodes = (require_node('sources', source), require_node('sinks', sink))
        config, _ = audio.load_config()
        labels = []
        for node in nodes:
            port = next(
                (
                    p
                    for p in audio.entries(node.get('ports'))
                    if p['name'] == node.get('active_port')
                ),
                {},
            )
            labels.append(audio.describe(node, port, config)['label'])
        detail = ' → '.join(labels)
        data = self.record(source, detail)
        self.check()
        if data:
            report('playback', detail)
            self.play(sink, data, raw=True)


def request_line():
    # Avoid buffering the release command along with the initial JSON request.
    data = bytearray()
    while len(data) < 4096:
        byte = os.read(sys.stdin.fileno(), 1)
        if not byte or byte == b'\n':
            return json.loads(data)
        data.extend(byte)
    raise ValueError('Invalid audio test request.')


def main():
    probe = Probe()
    signal.signal(signal.SIGTERM, probe.cancel)
    signal.signal(signal.SIGINT, probe.cancel)
    try:
        op = request_line().get('op')
        if op == 'speakers':
            probe.speakers()
        elif op == 'microphone':
            probe.microphone()
        else:
            raise ValueError('Unknown audio test.')
        report('done')
    except InterruptedError:
        pass
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        report(
            'error',
            error=str(error)
            if isinstance(error, ValueError)
            else 'Could not run the audio test.',
        )
    finally:
        probe.stop_child()


if __name__ == '__main__':
    main()
