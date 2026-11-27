"""Voice, conversation and desktop help for the desktop companion.

One process per request. It reads one JSON request line from stdin and writes
JSON event lines to stdout. While it works, later stdin lines carry `stop` and
`hold` for recordings and the shell's approval and intent replies.

- `warm` starts Lemonade and loads the chat, voice and transcription models.
- `models` reports the installed chat models and the current choice.
- `say` speaks text; `read` speaks the highlighted text.
- `turn` listens (hands-free or held), or takes typed text, files or a
  screenshot, then runs the behaviour's persona and tools through the
  Assistant's agent loop and speaks the reply while it streams.

SIGTERM cancels the request and its child processes.
"""

import array
import datetime
import http.client
import json
import os
from pathlib import Path
import queue
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave

HERE = Path(__file__).resolve().parent
DESKTOP = HERE.parent
# The Assistant backend owns Lemonade discovery, credentials, on-demand start,
# stream parsing, tools, approvals and context limits; the companion adds a
# persona, a tool selection and its own desktop tools.
sys.path.insert(0, str(DESKTOP / 'drawers/assistant'))
import backend as lemonade  # noqa: E402

Files = lemonade.Files
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
DATA = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
MEMORY = DATA / 'companion/memory.md'
BEHAVIORS = json.loads((HERE / 'behaviors.json').read_text())
TTS_MODEL = 'kokoro-v1'
TRANSCRIBERS = (
    'Whisper-Large-v3-Turbo',
    'Whisper-Small',
    'Whisper-Medium',
    'Whisper-Base',
    'Whisper-Large-v3',
    'Whisper-Tiny',
)
WHISPER_FILES = ('small', 'base', 'tiny', 'medium', 'large-v3-turbo', 'large-v3')
FPS = 30
RATE = 16000
FRAME_BYTES = RATE * 2 * 30 // 1000
MAX_RECORDING = 30
SPOKEN_LIMIT = {'all': 900, 'summary': 320}
TOOL_GROUPS = {
    'desktop': ('microphone', *lemonade.DESKTOP_TOOLS),
    'research': ('web_search', 'read_web_page', 'search_lyrics', 'get_song_lyrics'),
    'library': ('search_spaces', 'space_filters'),
    'inspect': ('inspect_system', 'read_file', 'list_directory', 'search_files'),
    'changes': ('run_command', 'write_file'),
}
WEATHER = {
    0: 'clear',
    1: 'mostly clear',
    2: 'partly cloudy',
    3: 'cloudy',
    45: 'foggy',
    48: 'foggy',
    51: 'light drizzle',
    53: 'drizzle',
    55: 'heavy drizzle',
    61: 'light rain',
    63: 'rain',
    65: 'heavy rain',
    71: 'light snow',
    73: 'snow',
    75: 'heavy snow',
    80: 'rain showers',
    81: 'rain showers',
    82: 'heavy showers',
    95: 'thunderstorm',
}


def tool(name, description, properties=None, required=()):
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': description,
            'parameters': {
                'type': 'object',
                'properties': properties or {},
                'required': list(required),
            },
        },
    }


DESKTOP_TOOLS = [
    tool(
        'media_control',
        'Control the music or video player, or ask what is playing.',
        {
            'action': {
                'type': 'string',
                'enum': ['play', 'pause', 'toggle', 'next', 'previous', 'status'],
            }
        },
        ['action'],
    ),
    tool(
        'set_volume',
        'Set or change the speaker volume, or mute it.',
        {
            'level': {'type': 'integer', 'minimum': 0, 'maximum': 100},
            'change': {'type': 'integer', 'minimum': -100, 'maximum': 100},
            'mute': {'type': 'boolean'},
        },
    ),
    tool(
        'play_space_result',
        'Play or open a result in its Space: songs, albums, '
        'artists, radio, TV channels, YouTube videos, movies, series, episodes and '
        'installed games. play=false only opens it. Use the exact ref returned by '
        'search_spaces or search_lyrics.',
        {'ref': {'type': 'string'}, 'play': {'type': 'boolean'}},
        ['ref'],
    ),
    tool('weather', 'Current weather and the next days for the user location.'),
    tool(
        'look_at_screen',
        'Look at the screen to answer a question about it. Use only when asked.',
        {'question': {'type': 'string'}},
        ['question'],
    ),
    tool(
        'read_selection',
        'Read the highlighted text aloud. Afterwards reply with only a few words.',
    ),
    tool(
        'recent_notifications',
        'List recent desktop notifications. Use only when asked.',
        {'count': {'type': 'integer', 'minimum': 1, 'maximum': 20}},
    ),
    tool(
        'remember',
        'Save a lasting fact or preference about the user, such as their name or '
        'favourite things, so you know it in later conversations. Call it whenever '
        'they tell you something worth keeping or ask you to remember something.',
        {'fact': {'type': 'string'}},
        ['fact'],
    ),
    tool(
        'forget',
        'Forget remembered facts that contain the given words.',
        {'fact': {'type': 'string'}},
        ['fact'],
    ),
    tool(
        'set_behavior',
        'Switch how you behave: playful (default), friend (for kids), assistant, or quiet.',
        {'behavior': {'type': 'string', 'enum': sorted(BEHAVIORS)}},
        ['behavior'],
    ),
    tool(
        'goodbye', 'Close the companion when the user says goodbye or asks you to go.'
    ),
]
# Desktop tools the shell carries out, through `intent` events and replies.
INTENTS = {
    'media_control',
    'set_behavior',
    'goodbye',
}


class Failure(Exception):
    """A request failure with a kind the shell can phrase for the user."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


CHILDREN = set()
WORKDIR = None
OUTPUT = threading.Lock()


def emit(value):
    with OUTPUT:
        sys.stdout.write(json.dumps(value, ensure_ascii=False) + '\n')
        sys.stdout.flush()


class Input:
    """Unbuffered stdin lines, so select() never misses a line already read."""

    buffer = b''

    @classmethod
    def line(cls, timeout=None):
        """The next line, '' at EOF, or None when the timeout passes first."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while b'\n' not in cls.buffer:
            wait = None if deadline is None else max(0, deadline - time.monotonic())
            if not select.select([0], [], [], wait)[0]:
                return None
            chunk = os.read(0, 4096)
            if not chunk:
                line, cls.buffer = cls.buffer, b''
                return line.decode(errors='replace')
            cls.buffer += chunk
        line, _, cls.buffer = cls.buffer.partition(b'\n')
        return line.decode(errors='replace')


class Router:
    """Reads stdin after the request: recording controls and shell replies."""

    def __init__(self):
        self.stop = threading.Event()
        self.hold = threading.Event()
        self.closed = False
        self.replies = {}
        self.ready = threading.Condition()
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while True:
            line = Input.line()
            if line == '':
                with self.ready:
                    self.closed = True
                    self.ready.notify_all()
                self.stop.set()
                return
            text = line.strip()
            if text == 'stop':
                self.stop.set()
            elif text == 'hold':
                self.hold.set()
            else:
                try:
                    value = json.loads(text)
                except ValueError:
                    continue
                if isinstance(value, dict) and isinstance(value.get('id'), str):
                    with self.ready:
                        self.replies[(value.get('type'), value['id'])] = value
                        self.ready.notify_all()

    def wait(self, kind, identifier, timeout):
        with self.ready:
            self.ready.wait_for(
                lambda: (kind, identifier) in self.replies or self.closed, timeout
            )
            return self.replies.pop((kind, identifier), None)


ROUTER = None


def cancel(_signum, _frame):
    for child in list(CHILDREN):
        try:
            child.terminate()
        except OSError:
            pass
    if WORKDIR:
        shutil.rmtree(WORKDIR, ignore_errors=True)
    try:
        # A signal can interrupt emit() while this thread holds OUTPUT.
        os.write(sys.stdout.fileno(), b'{"type":"cancelled"}\n')
    finally:
        os._exit(0)


def spawn(args, **options):
    options.setdefault('stdin', subprocess.DEVNULL)
    child = subprocess.Popen(args, **options)
    CHILDREN.add(child)
    return child


def run(args, timeout=10, data=None):
    child = spawn(
        args,
        stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = child.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise
    finally:
        CHILDREN.discard(child)
    return child.returncode, stdout, stderr


def settings():
    try:
        value = json.loads((CONFIG / 'quickshell/desktop/companion.json').read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def preference(name, key):
    try:
        value = json.loads((CONFIG / 'quickshell/desktop' / name).read_text())
    except (OSError, ValueError):
        return ''
    value = value.get(key) if isinstance(value, dict) else ''
    return value if isinstance(value, str) else ''


def clean(text):
    """Text that reads well aloud and in a bubble: no markup, emoji or symbols."""
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(
        r'`{1,3}|\*{1,3}|_{2,}|^#+\s*|^\s*(?:[-*•]|\d+[.)])\s+', '', text, flags=re.M
    )
    text = re.sub(r'[\U0001F000-\U0001FAFF☀-➿️‍]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


class Splitter:
    """Groups streamed text into sentences as soon as each one ends."""

    def __init__(self):
        self.pending = ''

    def feed(self, text):
        self.pending += text
        pieces = []
        while match := re.search(r'[.!?…]+["\')\]]*\s+|\n+', self.pending[12:]):
            end = 12 + match.end()
            pieces.append(self.pending[:end])
            self.pending = self.pending[end:]
        return pieces

    def flush(self):
        rest, self.pending = self.pending, ''
        return [rest] if rest.strip() else []


def sentences(chunks):
    splitter = Splitter()
    for chunk in chunks:
        for piece in splitter.feed(chunk):
            if text := clean(piece):
                yield text
    for piece in splitter.flush():
        if text := clean(piece):
            yield text


def envelope(pcm, rate):
    """Mouth openness per frame from loudness, narrowed for hissing consonants.

    Speech loudness is nearly flat across voiced sounds, so a power curve
    against the 99th percentile keeps vowels distinct from softer sounds, and
    the zero-crossing rate (high for s, f, sh) closes the mouth on fricatives.
    """
    samples = array.array('h')
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder != 'little':
        samples.byteswap()
    step = max(1, rate // FPS)
    frames = []
    for start in range(0, len(samples), step):
        window = samples[start : start + step]
        level = (sum(x * x for x in window) / len(window)) ** 0.5
        crossings = sum((a < 0) != (b < 0) for a, b in zip(window, window[1:]))
        frames.append((level, crossings / len(window)))
    if not frames:
        return []
    peak = sorted(level for level, _ in frames)[int(len(frames) * 0.99)] or 1
    values = []
    for level, crossings in frames:
        value = min(1.0, level / peak) ** 1.5 * (1 - 0.6 * min(1.0, crossings / 0.3))
        values.append(round(value, 2) if value > 0.06 else 0)
    return values


def roundness(text, frames):
    """Lip rounding per frame, spreading the text's o/u/w sounds over the audio."""
    letters = [letter for letter in text.lower() if not letter.isspace()]
    if not letters or not frames:
        return []
    return [
        0.8
        if letters[min(len(letters) - 1, index * len(letters) // frames)] in 'ouwоу'
        else 0
        for index in range(frames)
    ]


def level(frame):
    samples = array.array('h')
    samples.frombytes(frame)
    return (sum(x * x for x in samples) / max(1, len(samples))) ** 0.5


class Voice:
    """Synthesizes sentences ahead of playback, which stays strictly in order."""

    def __init__(self, url, voice, speed):
        self.url = url
        self.voice = voice
        self.speed = speed
        self.queue = queue.Queue(maxsize=2)
        self.error = None
        self.player = threading.Thread(target=self.play, daemon=True)
        self.player.start()

    def synthesize(self, text):
        payload = dict(
            model=TTS_MODEL,
            input=text,
            voice=self.voice,
            speed=self.speed,
            response_format='pcm',
        )
        with lemonade.request(
            self.url + '/v1/audio/speech', payload, timeout=90
        ) as response:
            kind = response.headers.get('Content-Type', '')
            match = re.search(r'rate=(\d+)', kind)
            pcm = response.read(64 * 1024 * 1024)
        if not pcm:
            raise Failure('voice', 'Lemonade returned no audio.')
        return int(match.group(1)) if match else 24000, pcm

    def say(self, text):
        if self.error:
            raise self.error
        rate, pcm = self.synthesize(text)
        path = Path(WORKDIR) / f'{time.monotonic_ns()}.wav'
        with wave.open(str(path), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(pcm)
        frames = envelope(pcm, rate)
        self.queue.put((text, path, frames, len(pcm) / 2 / rate))

    def play(self):
        while item := self.queue.get():
            text, path, frames, duration = item
            try:
                child = spawn(
                    [
                        'pw-play',
                        '--media-role=Communication',
                        '-P',
                        '{ media.name = "Companion" application.name = "Desktop companion" }',
                        str(path),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except OSError as exc:
                self.error = Failure('voice', f'Could not play audio: {exc}')
                emit(dict(type='line', text=text, duration=duration))
                continue
            emit(
                dict(
                    type='speech',
                    text=text,
                    envelope=frames,
                    round=roundness(text, len(frames)),
                    fps=FPS,
                    duration=duration,
                )
            )
            _, stderr = child.communicate()
            CHILDREN.discard(child)
            path.unlink(missing_ok=True)
            if child.returncode and not self.error:
                self.error = Failure('voice', stderr.decode(errors='replace')[-300:])

    def finish(self):
        self.queue.put(None)
        self.player.join()


class Text:
    """Voiceless output: sentences paced at a comfortable reading speed."""

    def __init__(self):
        self.ready = time.monotonic()

    def say(self, text):
        time.sleep(max(0, self.ready - time.monotonic()))
        duration = 0.8 + len(text) / 13
        emit(dict(type='line', text=text, duration=duration))
        self.ready = time.monotonic() + duration

    def finish(self):
        time.sleep(max(0, self.ready - time.monotonic()))


class Speaker:
    """Speaks the conversational part of a streamed answer; the rest is detail.

    `all` speaks everything except code, up to a length limit; `summary` stops
    after the first paragraph or at the first list, table or code block.
    """

    def __init__(self, output, mode):
        self.output = output
        self.mode = mode
        self.splitter = Splitter()
        self.raw = ''
        self.spoken = []
        self.limit = SPOKEN_LIMIT.get(mode, 900)
        self.finished = mode not in SPOKEN_LIMIT
        self.paragraph = False
        self.code = False
        self.tools = False
        # The stream reader can keep receiving text and dispatching tools while
        # Kokoro synthesizes a sentence or the bubble waits for its next line.
        self.pending = queue.SimpleQueue()
        self.output_error = None
        self.worker = threading.Thread(target=self.deliver, daemon=True)
        self.worker.start()

    def feed(self, text):
        if self.tools:
            self.round()
        self.raw += text
        for piece in self.splitter.feed(text):
            self.consider(piece)

    def round(self):
        """Tools ran; finish the preface, then speak the next answer's paragraph."""
        self.tools = False
        for piece in self.splitter.flush():
            self.consider(piece)
        if self.paragraph:
            self.finished = self.paragraph = False

    def say(self, text):
        """Speak text outside the answer stream, such as a read selection."""
        self.pending.put(text)

    def deliver(self):
        try:
            while (text := self.pending.get()) is not None:
                try:
                    self.output.say(text)
                except (OSError, ValueError, Failure, http.client.HTTPException) as exc:
                    self.fallback(exc)
                    self.output.say(text)
            self.output.finish()
        except Exception as exc:
            self.output_error = exc

    def fallback(self, exc):
        # Keep what was spoken; the rest of the reply reaches the bubble only.
        if isinstance(self.output, Voice):
            self.output.finish()
            self.output = Text()
            emit(dict(type='notice', error=str(exc)))
        else:
            raise exc

    def consider(self, piece):
        if self.finished:
            return
        kept = []
        for line in piece.splitlines(keepends=True):
            stripped = line.strip()
            if re.match(r'^(```|~~~)', stripped):
                self.code = not self.code
                if self.spoken and self.mode == 'summary':
                    self.finished = True
                    break
                continue
            if self.code:
                continue
            structural = re.match(r'^(#|\||[-*•] |\d+[.)] )', stripped)
            if (self.spoken or kept) and self.mode == 'summary' and structural:
                self.finished = True
                break
            kept.append(line)
        text = clean(''.join(kept))
        if not text:
            return
        if (
            self.spoken
            and sum(len(row) for row in self.spoken) + len(text) > self.limit
        ):
            self.finished = True
            return
        self.spoken.append(text)
        self.say(text)
        if self.mode == 'summary' and re.search(r'\n\s*\n', piece):
            self.finished = self.paragraph = True

    def finish(self):
        for piece in self.splitter.flush():
            self.consider(piece)
        self.pending.put(None)
        self.worker.join()
        if self.output_error:
            raise self.output_error

    @property
    def details(self):
        """The full answer when it holds more than was spoken."""
        answer = self.raw.strip()
        structured = re.search(r'^(```|~~~|#|\||[-*•] |\d+[.)] )', answer, re.M)
        unspoken = len(clean(answer)) - len(' '.join(self.spoken))
        return answer if structured or unspoken > 60 else ''


def connect(start):
    """Lemonade's URL, starting the user service when asked; None when offline."""
    try:
        snapshot = lemonade.control('connect' if start else 'status')
    except (
        OSError,
        ValueError,
        http.client.HTTPException,
        subprocess.SubprocessError,
    ) as exc:
        raise Failure('offline', str(exc)) from exc
    # A refresh error leaves inference usable; requests report real failures.
    if snapshot.get('online'):
        return snapshot['url']
    if start:
        raise Failure('offline', snapshot.get('error') or 'Lemonade is not running.')
    return None


def catalogue(url):
    return {
        row['id']: row
        for row in lemonade.get_json(url + '/v1/models?show_all=true').get('data', [])
        if isinstance(row, dict) and isinstance(row.get('id'), str)
    }


def downloaded(models, name):
    return models.get(name, {}).get('downloaded') is True


def voice_for(url):
    """Speech when the text-to-speech model is downloaded; it never downloads one."""
    try:
        models = catalogue(url) if url else {}
    except (OSError, ValueError) as exc:
        emit(dict(type='notice', error=str(exc)))
        models = {}
    if not downloaded(models, TTS_MODEL):
        return Text()
    config = settings()
    voice = config.get('voice') if isinstance(config.get('voice'), str) else ''
    speed = config.get('speed')
    speed = speed if isinstance(speed, (int, float)) and 0.5 <= speed <= 2 else 1.0
    return Voice(url, voice or 'af_heart', speed)


def chat_models(url):
    return lemonade.chat_models({'data': list(catalogue(url).values())}) if url else []


def preferred_model(rows):
    entries = {row['id']: row for row in rows}
    for wanted in (settings().get('model'), preference('assistant.json', 'model')):
        if isinstance(wanted, str) and wanted in entries:
            return entries[wanted]
    return next(
        (row for row in rows if row['supportsTools']), rows[0] if rows else None
    )


def report_models(rows):
    entry = preferred_model(rows)
    emit(
        dict(
            type='models',
            selected=entry['id'] if entry else '',
            models=[
                dict(id=row['id'], vision='vision' in row['labels']) for row in rows
            ],
        )
    )
    return entry


def transcriber(url):
    models = catalogue(url)
    wanted = settings().get('transcriber')
    for name in (wanted, *TRANSCRIBERS):
        if isinstance(name, str) and downloaded(models, name):
            return name
    return ''


def warm():
    """Start Lemonade and load what conversations need, so the first is quick."""
    url = connect(True)
    entry = report_models(chat_models(url))
    if not entry:
        raise Failure('model', 'No local chat model is downloaded.')
    model = entry['id']
    models = catalogue(url)
    loads = []
    backend = preference('assistant.json', 'backend')
    options = {}
    if entry['recipe'] == 'llamacpp' and re.fullmatch(r'[a-z0-9_-]+', backend or '-'):
        if backend != 'auto':
            options['llamacpp_backend'] = backend
    loads.append((model, options))
    if downloaded(models, TTS_MODEL):
        loads.append((TTS_MODEL, {}))
    heard = transcriber(url)
    if heard:
        loads.append((heard, {}))
    emit(dict(type='warming', model=model))
    for name, extra in loads:
        try:
            with lemonade.request(
                url + '/v1/load', dict(model_name=name, **extra), timeout=900
            ) as response:
                json.load(response)
        except (OSError, ValueError) as exc:
            emit(dict(type='notice', error=f'{name}: {exc}'))
    emit(
        dict(
            type='ready',
            model=model,
            voice=downloaded(models, TTS_MODEL),
            transcriber=heard,
            vision='vision' in entry['labels'],
        )
    )


def record(mode, follow_up):
    """Record until silence ends speech ("auto") or until `stop` ("hold").

    A `hold` line turns a hands-free recording into a held one. Returns the WAV
    path, or None with "silent" (no speech) or "short" (released too soon).
    """
    try:
        child = spawn(
            [
                'pw-record',
                '--raw',
                '--media-role=Communication',
                '--properties={ application.id = "dotfiles.companion" }',
                '--rate=16000',
                '--channels=1',
                '--format=s16',
                '-',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise Failure('microphone', str(exc)) from exc
    started = time.monotonic()
    audio = bytearray()
    pending = bytearray()
    floor = 0.0
    voiced = silence = frames = 0
    speech_at = None
    hold = mode == 'hold'
    patience = 5 if follow_up else 8
    fd = child.stdout.fileno()
    ended = stream_closed = False
    remaining = None
    while not ended:
        now = time.monotonic()
        hold = hold or ROUTER.hold.is_set()
        if ROUTER.stop.is_set() or now - started > MAX_RECORDING:
            break
        if not hold and speech_at is None and now - started > patience:
            break
        if audio and follow_up:
            seconds = (
                max(0, int(patience - (now - started) + 0.999))
                if speech_at is None and not hold
                else 0
            )
            if seconds != remaining:
                remaining = seconds
                emit(dict(type='listen_wait', seconds=remaining))
        if not select.select([fd], [], [], 0.05)[0]:
            if child.poll() is not None:
                stream_closed = True
                break
            continue
        data = os.read(fd, 4096)
        if not data:
            stream_closed = True
            break
        if not audio:
            emit(dict(type='listening'))
        audio += data
        pending += data
        while len(pending) >= FRAME_BYTES and not ended:
            frame, pending = pending[:FRAME_BYTES], pending[FRAME_BYTES:]
            loudness = level(frame)
            frames += 1
            if frames % 2 == 0:
                emit(dict(type='level', value=round(min(1, loudness / 4000) ** 0.6, 2)))
            # Learn the floor from quiet frames so speaking immediately doesn't
            # train the detector on the user's voice. Use a lower bar to end speech.
            threshold = (
                max(floor * 2.5, 180) if speech_at is None else max(floor * 1.5, 120)
            )
            if loudness > threshold:
                voiced += 1
                silence = 0
                if voiced >= 3 and speech_at is None:
                    speech_at = max(0, len(audio) - len(pending) - FRAME_BYTES * 14)
            else:
                voiced = 0
                if speech_at is None:
                    floor = 0.95 * floor + 0.05 * loudness
                else:
                    silence += 1
            ended = not hold and speech_at is not None and silence >= 27
    if child.poll() is None:
        if not stream_closed:
            child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    CHILDREN.discard(child)
    if (stream_closed and child.returncode) or (not audio and not ROUTER.stop.is_set()):
        detail = child.stderr.read().decode(errors='replace').strip()
        raise Failure('microphone', detail or 'The microphone delivered no audio.')
    if hold and len(audio) < RATE * 2 * 0.4:
        return None, 'short'
    if not hold and speech_at is None:
        return None, 'silent'
    path = Path(WORKDIR) / 'question.wav'
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(bytes(audio[speech_at or 0 :]))
    return path, ''


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def lemonade_transcribe(url, model, path, language):
    boundary = uuid.uuid4().hex
    fields = [('model', model)] + (
        [('language', language)] if language != 'auto' else []
    )
    body = b''.join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields
    )
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        'filename="question.wav"\r\nContent-Type: audio/wav\r\n\r\n'
    ).encode()
    body += path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
    keys = lemonade.api_keys(lemonade.SCOPE)
    if key := keys.get('LEMONADE_API_KEY') or keys.get('LEMONADE_ADMIN_API_KEY'):
        headers['Authorization'] = f'Bearer {key}'
    # Like the Assistant's requests: no proxy and no redirects.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(
        url + '/v1/audio/transcriptions', data=body, headers=headers
    )
    with opener.open(request, timeout=120) as response:
        value = json.load(response)
    return value.get('text') if isinstance(value, dict) else None


def whisper_cli(path, language):
    name = settings().get('speechModel') or preference('speech.json', 'model')
    folder = DATA / 'voxtype/models'
    model = next(
        (
            folder / f'ggml-{candidate}.bin'
            for candidate in (name, *WHISPER_FILES)
            if isinstance(candidate, str)
            and re.fullmatch(r'[a-z0-9.-]+', candidate)
            and (folder / f'ggml-{candidate}.bin').is_file()
        ),
        None,
    )
    if not model:
        raise Failure('speech', 'No speech recognition model is set up.')
    output = Path(WORKDIR) / 'question'
    try:
        code, _, stderr = run(
            [
                'whisper-cli',
                '-m',
                str(model),
                '-l',
                language,
                '-f',
                str(path),
                '-otxt',
                '-of',
                str(output),
                '-np',
                '-t',
                str(min(8, os.cpu_count() or 1)),
            ],
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Failure('speech', str(exc)) from exc
    if code:
        raise Failure('speech', stderr.decode(errors='replace').strip()[-300:])
    try:
        return output.with_suffix('.txt').read_text(errors='replace')
    except OSError as exc:
        raise Failure('speech', str(exc)) from exc


def transcribe(path, url):
    language = (
        settings().get('language') or preference('speech.json', 'language') or 'auto'
    )
    text = None
    try:
        if url and (model := transcriber(url)):
            text = lemonade_transcribe(url, model, path, language)
            if not isinstance(text, str):
                raise ValueError('Lemonade returned an invalid transcript.')
    except (OSError, ValueError, http.client.HTTPException) as exc:
        emit(dict(type='notice', error=f'Using local Whisper transcription: {exc}'))
        text = None
    if text is None:
        text = whisper_cli(path, language)
    # Whisper describes silence and noise in brackets; that is not a question.
    return clean(re.sub(r'\[[^\]]*\]|\([^)]*\)|\*[^*]*\*', ' ', text))


def selection():
    try:
        code, stdout, _ = run(['wl-paste', '--primary', '--no-newline'], timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return stdout.decode(errors='replace').strip()[:6000] if code == 0 else ''


def screenshot():
    """The focused output as an image attachment (the companion included)."""
    try:
        _, stdout, _ = run(['hyprctl', '-j', 'monitors'], timeout=5)
        name = next(
            (row['name'] for row in json.loads(stdout) if row.get('focused')), ''
        )
        code, image, stderr = run(
            ['grim', *(['-o', name] if name else []), '-'], timeout=10
        )
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        raise Failure('screen', str(exc)) from exc
    if code or not image:
        raise Failure('screen', stderr.decode(errors='replace').strip() or 'No image.')
    return Files.snapshot('screen.png', image)


def look(url, model, entry, question):
    if 'vision' not in entry['labels']:
        return {'error': 'The current model cannot see images.'}
    content = Files.message_content(
        {
            'content': question or 'What is on the screen?',
            'attachments': [screenshot()],
        },
        True,
    )
    payload = dict(
        model=model,
        stream=False,
        max_tokens=500,
        enable_thinking=False,
        messages=[
            {
                'role': 'system',
                'content': 'Describe what this screenshot shows that helps answer the '
                'question. Quote visible text that matters. Be concise.',
            },
            {'role': 'user', 'content': content},
        ],
    )
    with lemonade.request(
        url + '/v1/chat/completions', payload, timeout=300
    ) as response:
        data = json.load(response)
    return {'screen': data['choices'][0]['message'].get('content', '')}


def weather():
    try:
        _, stdout, _ = run(
            [sys.executable, str(DESKTOP / 'drawers/weather/backend.py')],
            timeout=25,
            data=b'{"op": "island"}\n',
        )
        data = json.loads(stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'error': 'The weather is unavailable right now.'}
    if data.get('error'):
        return {'error': data['error']}
    forecast = data.get('weather') or {}
    now = forecast.get('current') or {}
    return {
        'location': (data.get('location') or {}).get('name', ''),
        'now': {
            'temperature_c': now.get('temperature'),
            'feels_like_c': now.get('feelsLike'),
            'conditions': WEATHER.get(now.get('code'), 'unsettled'),
            'humidity_percent': now.get('humidity'),
            'wind_kmh': now.get('wind'),
            'daytime': now.get('isDay'),
        },
        'days': [
            {
                'date': day.get('date'),
                'high_c': day.get('high'),
                'low_c': day.get('low'),
                'rain_chance_percent': day.get('rain'),
                'outlook': day.get('outlook'),
            }
            for day in (forecast.get('daily') or [])[:3]
        ],
    }


def notifications(count):
    shell = CONFIG / 'quickshell/desktop/shell.qml'
    try:
        code, stdout, _ = run(
            [
                'qs',
                'ipc',
                '--path',
                str(shell),
                'call',
                'notifications',
                'recent',
                str(count),
            ],
            timeout=5,
        )
        rows = json.loads(stdout) if code == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        rows = None
    if not isinstance(rows, list):
        return {'error': 'Notifications are unavailable.'}
    return {'notifications': rows}


def volume(args):
    sink = '@DEFAULT_AUDIO_SINK@'
    mute, value, change = args.get('mute'), args.get('level'), args.get('change')
    commands = []
    if isinstance(mute, bool):
        commands.append(['wpctl', 'set-mute', sink, '1' if mute else '0'])
    if isinstance(value, int) and 0 <= value <= 100:
        commands.append(['wpctl', 'set-volume', '-l', '1.0', sink, f'{value}%'])
    elif isinstance(change, int) and change:
        step = f'{min(100, abs(change))}%{"+" if change > 0 else "-"}'
        commands.append(['wpctl', 'set-volume', '-l', '1.0', sink, step])
    for command in [*commands, ['wpctl', 'get-volume', sink]]:
        code, stdout, stderr = run(command, timeout=5)
        if code:
            return {
                'error': stderr.decode(errors='replace').strip()
                or 'Volume change failed.'
            }
    match = re.search(r'([\d.]+)', stdout.decode())
    return {
        'volume_percent': round(float(match.group(1)) * 100) if match else None,
        'muted': b'MUTED' in stdout,
    }


def memory():
    try:
        lines = MEMORY.read_text().splitlines()
    except OSError:
        return []
    return [
        line[2:].strip() for line in lines if line.startswith('- ') and line[2:].strip()
    ]


def save_memory(facts):
    MEMORY.parent.mkdir(parents=True, exist_ok=True)
    staged = MEMORY.with_name('.memory.md.tmp')
    staged.write_text(
        '# Companion memory\n\nOne fact per line; edit or delete freely.\n\n'
        + ''.join(f'- {fact}\n' for fact in facts)
    )
    staged.replace(MEMORY)


def remember(fact):
    fact = clean(fact)[:200]
    if not fact:
        return {'error': 'Nothing to remember.'}
    facts = memory()
    if fact.casefold() not in (row.casefold() for row in facts):
        facts = (facts + [fact])[-60:]
        save_memory(facts)
    return {'remembered': fact}


def forget(words):
    needle = clean(words).casefold()
    facts = memory()
    kept = [
        row
        for row in facts
        if not needle or (needle not in row.casefold() and row.casefold() not in needle)
    ]
    save_memory(kept)
    return {'forgotten': len(facts) - len(kept)}


def open_space(args):
    """Hand a search result to the desktop shell, as a card's Open or Play does."""
    item = lemonade.SPACE_RESULTS.get(str(args.get('ref', '')))
    if not item:
        return {
            'error': 'That result is not available. Search again with search_spaces or search_lyrics.'
        }
    play = args.get('play') is not False and item.get('playable') is True
    request = json.dumps(
        {'space': item['space'], 'payload': item['payload'], 'play': play},
        ensure_ascii=False,
    )
    shell = CONFIG / 'quickshell/desktop/shell.qml'
    try:
        code, stdout, stderr = run(
            ['qs', 'ipc', '--path', str(shell), 'call', 'spaces', 'open', request],
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {'error': 'The desktop shell is unavailable.'}
    message = (stdout or stderr).decode(errors='replace').strip()
    if code or message:
        return {'error': message or 'The desktop shell did not open it.'}
    return {
        'opened': item.get('title', ''),
        'space': item['space'],
        'playing': play,
        **(
            {}
            if play or args.get('play') is False
            else {'note': 'This kind opens without playing.'}
        ),
    }


def intent(name, arguments):
    """Ask the shell to carry out a desktop action and wait for its answer."""
    identifier = uuid.uuid4().hex
    emit(dict(type='intent', id=identifier, name=name, arguments=arguments))
    reply = ROUTER.wait('intent', identifier, 15)
    if not reply:
        return {'error': 'The desktop did not answer.'}
    result = reply.get('result')
    return result if isinstance(result, dict) else {'error': 'Invalid desktop answer.'}


def desktop_tool(name, args, speaker, url, model, entry):
    if name in INTENTS:
        return intent(name, args)
    if name == 'play_space_result':
        return open_space(args)
    if name == 'weather':
        return weather()
    if name == 'look_at_screen':
        return look(url, model, entry, str(args.get('question', '')))
    if name == 'read_selection':
        text = selection()
        if not text:
            return {'error': 'Nothing is highlighted.'}
        for piece in sentences([text]):
            speaker.say(piece)
        return {'read_aloud': True, 'characters': len(text)}
    if name == 'recent_notifications':
        count = args.get('count')
        return notifications(count if isinstance(count, int) and 0 < count <= 20 else 5)
    if name == 'set_volume':
        return volume(args)
    if name == 'remember':
        return remember(str(args.get('fact', '')))
    if name == 'forget':
        return forget(str(args.get('fact', '')))
    return {'error': f'Unknown tool: {name}'}


def instructions(behavior):
    name = settings().get('name') or 'Pip'
    name = name.strip()[:24] if isinstance(name, str) and name.strip() else 'Pip'
    now = datetime.datetime.now()
    text = behavior['persona'].format(name=name)
    text += f'\n\nIt is {now:%A, %d %B %Y, %H:%M}.'
    text += (
        '\n\nUse search_spaces for questions about the media library. Keep the '
        "user's filters, and summarize recommendations in the reply. If asked "
        'to play or open a result, call play_space_result with its returned ref. '
        'Only use refs returned by your tools. Use source URLs for web research.'
    )
    if 'research' in behavior.get('tools', []):
        text += '\n\n' + lemonade.LYRICS_INSTRUCTIONS
    text += (
        '\n\nYou forget everything between conversations except what you save '
        'with the remember tool. When asked to remember something, call remember '
        'first; never say you will remember without calling it.'
    )
    if facts := memory():
        text += ' Things you remember (keep them current with remember and forget):\n'
        text += '\n'.join(f'- {fact}' for fact in facts)[:4000]
    return text


def converse(url, behavior, question, attachments, request):
    entry = preferred_model(chat_models(url))
    if not entry:
        raise Failure('model', 'No local chat model is downloaded.')
    model = entry['id']
    groups = behavior.get('tools', [])
    backend_names = {name for group in groups for name in TOOL_GROUPS.get(group, ())}
    offered = [
        row for row in lemonade.TOOLS if row['function']['name'] in backend_names
    ]
    if 'desktop' in groups:
        offered += DESKTOP_TOOLS
    offered_names = {row['function']['name'] for row in offered}
    history = [
        row
        for row in request.get('history', [])[-12:]
        if isinstance(row, dict)
        and row.get('role') in ('user', 'assistant')
        and isinstance(row.get('content'), str)
    ]
    current = dict(role='user', content=question)
    if attachments:
        current['attachments'] = attachments
    value = dict(
        model=model,
        messages=[*history, current],
        thinking='off',
        backend=preference('assistant.json', 'backend') or 'auto',
        desktop_context=request.get('context'),
    )
    output = voice_for(url) if behavior.get('voice') else Text()
    speaker = Speaker(
        output, behavior.get('speak', 'all') if behavior.get('voice') else 'summary'
    )
    state = {}
    handoff_results = []

    def tap(event):
        kind = event.get('type')
        if kind == 'delta':
            speaker.feed(event.get('text') or '')
        elif kind == 'tool':
            speaker.tools = True
            activity = dict(event.get('activity') or {})
            if activity.get('name') in lemonade.HANDOFF_TOOLS and activity.get(
                'state'
            ) in ('completed', 'failed'):
                handoff_results.append(
                    dict(
                        name=activity['name'],
                        args=activity.get('arguments', {}),
                        result=activity.get('result')
                        or {'error': activity.get('summary', '')},
                    )
                )
            result = activity.pop('result', None) or {}
            if activity.get('name') == 'window' and result.get('confirmed'):
                activity['destination'] = result.get('window', {}).get('monitor')
            emit(dict(type='tool', activity=activity))
        elif kind in ('done', 'error', 'context'):
            state[kind] = event

    def delegate(call):
        function = (
            call.get('function') if isinstance(call.get('function'), dict) else {}
        )
        name = function.get('name') if isinstance(function.get('name'), str) else ''
        if name in backend_names:
            return None
        if name not in offered_names:
            result = {'error': f'{name[:60] or "That tool"} is not available here.'}
        else:
            try:
                args = json.loads(function.get('arguments') or '{}')
                if not isinstance(args, dict):
                    raise ValueError('Tool arguments must be an object.')
                emit(dict(type='action', name=name, arguments=args))
                speaker.tools = True
                result = desktop_tool(name, args, speaker, url, model, entry)
            except (OSError, ValueError, KeyError, TypeError, Failure) as exc:
                result = {'error': str(exc) or type(exc).__name__}
        return {
            'role': 'tool',
            'tool_call_id': call.get('id', ''),
            'content': json.dumps(
                {'untrusted_tool_result': result}, ensure_ascii=False
            ),
        }

    def approve(identifier):
        reply = ROUTER.wait('approval', identifier, lemonade.APPROVAL_SECONDS)
        if reply is None:
            return False, 'Approval expired before the operation was approved.'
        if reply.get('approved') is True:
            return True, ''
        return False, 'The user rejected this operation.'

    original = lemonade.emit
    lemonade.emit = tap
    try:
        lemonade.chat(
            value,
            instructions=instructions(behavior),
            tools=offered,
            delegate=delegate,
            approve=approve,
            downloaded_only=True,
        )
    finally:
        lemonade.emit = original
        speaker.finish()
    if 'error' in state:
        raise Failure('model', state['error'].get('error', ''))
    done = state.get('done', {})
    answer = speaker.raw.strip()
    if not answer and not done.get('tool_context'):
        raise Failure('model', 'The model returned an empty answer.')
    emit(
        dict(
            type='reply',
            id=uuid.uuid4().hex,
            model=model,
            question=question,
            text=answer,
            results=handoff_results,
            tool_context=done.get('tool_context') or [],
        )
    )
    if details := speaker.details:
        emit(dict(type='details', text=details))


def turn(request):
    behavior = BEHAVIORS.get(request.get('behavior')) or BEHAVIORS['playful']
    url = None
    attachments = []
    listen = request.get('listen')
    if listen in ('auto', 'hold'):
        path, reason = record(listen, request.get('followUp') is True)
        if not path:
            emit(dict(type='nothing', reason=reason))
            return
        emit({'type': 'transcribing'})
        try:
            url = connect(False)
        except Failure as exc:
            emit(dict(type='notice', error=str(exc)))
        question = transcribe(path, url)
        if not question:
            emit(dict(type='nothing', reason='silent'))
            return
        emit(dict(type='heard', text=question))
    else:
        question = str(request.get('text', '')).strip()[:4000]
        files = request.get('files')
        if isinstance(files, list) and files:
            prepared = Files.prepare([str(url) for url in files][:6])
            attachments = prepared['items']
            if prepared['error']:
                emit(dict(type='notice', error=prepared['error']))
        if request.get('screen') is True:
            attachments.append(screenshot())
        if not question:
            question = (
                "What's on my screen?"
                if request.get('screen') is True
                else 'What is this? Tell me about it.'
                if attachments
                else ''
            )
        if not question:
            raise ValueError('Nothing to answer.')
    emit({'type': 'thinking'})
    converse(url or connect(True), behavior, question, attachments, request)


def speak_text(text, start, voice=True):
    url = connect(start)
    speaker = Speaker(voice_for(url) if voice else Text(), 'all')
    speaker.limit = 6000
    try:
        speaker.feed(text)
    finally:
        speaker.finish()


def main():
    global WORKDIR, ROUTER
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    runtime = os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir()
    WORKDIR = tempfile.mkdtemp(prefix='companion-', dir=runtime)
    try:
        request = json.loads(Input.line() or '{}')
        ROUTER = Router()
        op = request.get('op')
        if op == 'warm':
            warm()
        elif op == 'models':
            report_models(chat_models(connect(False)))
        elif op == 'say':
            text = str(request.get('text', ''))[:6000]
            if not clean(text):
                raise ValueError('Nothing to say.')
            speak_text(
                text, request.get('start') is True, request.get('voice') is not False
            )
        elif op == 'read':
            text = selection()
            if not text:
                emit(dict(type='nothing', reason='selection'))
            else:
                speak_text(text, True)
        elif op == 'turn':
            turn(request)
        else:
            raise ValueError('Unknown companion request.')
    except Failure as exc:
        emit(dict(type='error', kind=exc.kind, error=str(exc)))
    except urllib.error.HTTPError as exc:
        emit(
            dict(
                type='error', kind='model', error=f'Lemonade returned HTTP {exc.code}.'
            )
        )
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as exc:
        emit(dict(type='error', kind='other', error=str(exc) or type(exc).__name__))
    finally:
        shutil.rmtree(WORKDIR, ignore_errors=True)
    emit({'type': 'done'})


if __name__ == '__main__':
    main()
