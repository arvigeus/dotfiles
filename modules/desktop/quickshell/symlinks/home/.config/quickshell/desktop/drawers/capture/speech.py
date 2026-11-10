"""Speech jobs owned by desktop-capture.service, independent of drawer lifetime."""

import ctypes
import ctypes.util
import datetime
import functools
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
import wave
import uuid

DEFAULTS = {'language': 'auto', 'mode': 'transcribe', 'paste': False, 'model': 'small'}
# Multilingual checkpoints. Whisper's original vocabulary has 99 languages;
# large-v3/turbo add Cantonese. Names/sizes describe downloadable releases.
MODELS = {
    'tiny': {'name': 'Whisper Tiny', 'size': '75 MB', 'languages': 99},
    'base': {'name': 'Whisper Base', 'size': '142 MB', 'languages': 99},
    'small': {'name': 'Whisper Small', 'size': '466 MB', 'languages': 99},
    'medium': {'name': 'Whisper Medium', 'size': '1.5 GB', 'languages': 99},
    'large-v3': {'name': 'Whisper Large v3', 'size': '3.1 GB', 'languages': 100},
    'large-v3-turbo': {
        'name': 'Whisper Large v3 Turbo',
        'size': '1.6 GB',
        'languages': 100,
    },
}
FILE_LIMIT = 1800
MEDIA_LIMIT = 6 * 60 * 60


@functools.lru_cache(maxsize=1)
def language_catalog():
    """Read names and IDs from the installed inference engine, without a model."""
    try:
        library = ctypes.CDLL(ctypes.util.find_library('whisper') or 'libwhisper.so')
        library.whisper_lang_max_id.argtypes = []
        library.whisper_lang_max_id.restype = ctypes.c_int
        for name in ('whisper_lang_str', 'whisper_lang_str_full'):
            function = getattr(library, name)
            function.argtypes = [ctypes.c_int]
            function.restype = ctypes.c_char_p
        return tuple(
            dict(
                id=index,
                code=library.whisper_lang_str(index).decode(),
                name=library.whisper_lang_str_full(index).decode().title(),
            )
            for index in range(library.whisper_lang_max_id() + 1)
        )
    except (OSError, AttributeError):
        # Audio-only recording and model setup remain available without the
        # engine. Transcription reports the missing package when requested.
        return ()


class SpeechNotification:
    """One replaceable notification, emitted without blocking capture controls."""

    def __init__(self):
        self.process = None
        self.pending = None
        self.identifier = 0
        self.next_update = 0
        self.deadline = 0
        self.disabled = False
        self.action = ''
        self.cancelling = False

    def update(self, title, body, progress=-1, finished=False, action=None):
        if not self.disabled:
            self.cancel_prompt()
            self.pending = (title, body, progress, finished, action)
            if finished:
                self.next_update = 0

    def cancel_prompt(self):
        if self.pending and self.pending[-1]:
            self.pending = None
        if self.process and self.action and not self.cancelling:
            # notify-send closes its notification when interrupted.
            self.process.send_signal(signal.SIGINT)
            self.cancelling = True
            self.deadline = time.monotonic() + 2

    @property
    def busy(self):
        return self.process is not None or self.pending is not None

    def tick(self):
        now = time.monotonic()
        selected = ''
        if self.process:
            if self.process.poll() is None:
                if now < self.deadline:
                    return selected
                if self.action and not self.cancelling:
                    self.cancel_prompt()
                    return selected
                self.process.kill()
            output, _ = self.process.communicate()
            lines = output.splitlines()
            if lines and lines[0].isdigit():
                self.identifier = int(lines[0])
                if (
                    self.process.returncode == 0
                    and not self.cancelling
                    and self.action in lines[1:]
                ):
                    selected = self.action
            elif not self.cancelling:
                self.disabled = True
                self.pending = None
            self.process = None
            self.action = ''
            self.cancelling = False
        if self.disabled or not self.pending or now < self.next_update:
            return selected
        title, body, progress, finished, action = self.pending
        self.pending = None
        command = [
            'notify-send',
            '--app-name=Speech',
            '--icon=audio-input-microphone',
            '--print-id',
            f'--replace-id={self.identifier}',
            # Own the prompt deadline so expiry withdraws its action too;
            # a notification server may keep timed-out cards in history.
            f'--expire-time={0 if action or not finished else 8000}',
            '--hint=boolean:suppress-sound:true',
        ]
        if not finished:
            command.append('--transient')
        if progress >= 0:
            command.append(f'--hint=int:value:{int(progress)}')
        if action:
            command.append(f'--action={action[0]}={action[1]}')
        command.extend([title, body])
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            self.action = action[0] if action else ''
            self.deadline = now + (30 if action else 2)
            self.next_update = now + 1
        except OSError:
            self.disabled = True
        return selected

    def close(self):
        if self.process:
            if self.process.poll() is None:
                if self.action:
                    self.process.send_signal(signal.SIGINT)
                else:
                    self.process.kill()
            try:
                self.process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate()
            self.process = None
        self.pending = None


def active_window():
    try:
        window = json.loads(
            subprocess.run(
                ['hyprctl', '-j', 'activewindow'],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout
        )
        address = window.get('address', '')
        if re.fullmatch(r'0x[0-9a-fA-F]+', address):
            return address, str(window.get('class', ''))
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        pass
    return '', ''


def paste_into(target):
    """Only address the original, still-focused application; never submit text."""
    if not re.fullmatch(r'0x[0-9a-fA-F]+', target[0]) or active_window() != target:
        return False
    terminal = re.search(
        r'kitty|alacritty|ghostty|wezterm|(^|\.)foot($|\.)|konsole|gnome-terminal',
        target[1],
        re.I,
    )
    mods = 'CTRL SHIFT' if terminal else 'CTRL'
    expression = (
        'hl.dsp.send_shortcut({ mods = "'
        + mods
        + '", key = "V", window = "address:'
        + target[0]
        + '" })'
    )
    try:
        subprocess.run(
            ['hyprctl', 'dispatch', expression],
            check=True,
            capture_output=True,
            timeout=2,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


class Speech:
    def __init__(
        self, directory, preference, folder, write, microphone, mute_microphone
    ):
        self.directory = Path(directory)
        self.preference = Path(preference)
        self.folder = Path(folder)
        self.write = write
        self.microphone = microphone
        self.mute_microphone = mute_microphone
        self.options = dict(DEFAULTS)
        try:
            saved = json.loads(self.preference.read_text())
            for key, value in saved.items():
                if self.valid_option(key, value):
                    self.options[key] = value
        except (OSError, ValueError, AttributeError):
            pass
        data = os.environ.get('XDG_DATA_HOME', '')
        data = Path(data) if os.path.isabs(data) else Path.home() / '.local/share'
        self.models_dir = data / 'voxtype/models'
        if self.options['language'] not in {item['code'] for item in self.languages()}:
            self.options['language'] = 'auto'
        self.config = Path(__file__).with_name('dictation.toml')
        self.notification = SpeechNotification()
        self.notified_progress = -1
        self.phase = 'idle'
        self.error = ''
        self.message = ''
        self.last_audio = ''
        self.process = None
        self.log = None
        self.temporary = None
        self.clipboards = []
        self.clipboard = None
        self.paste_blocked = True
        self.target = ('', '')
        self.job = {}
        self.result = {}
        self.progress = -1
        self.since = 0
        self.deadline = 0
        self.prompt_source = None
        self.restore_source = None
        self.open_microphone_controls = False
        self.controls_deadline = 0
        self.mute_restore_failed = False

    @staticmethod
    def valid_option(key, value):
        return (
            (
                key == 'language'
                and isinstance(value, str)
                and (
                    value == 'auto'
                    or any(item['code'] == value for item in language_catalog())
                )
            )
            or (key == 'mode' and value in ('transcribe', 'audio'))
            or (key == 'paste' and type(value) is bool)
            or (key == 'model' and isinstance(value, str) and value in MODELS)
        )

    @property
    def model(self):
        return self.model_path(self.options['model'])

    def model_path(self, name):
        return self.models_dir / f'ggml-{name}.bin'

    def model_ready(self, name=None):
        path = self.model_path(name or self.options['model'])
        return path.is_file() and path.stat().st_size > 0

    def languages(self, model=None):
        limit = MODELS[model or self.options['model']]['languages']
        return [dict(code='auto', name='Auto-detect')] + sorted(
            [
                dict(code=item['code'], name=item['name'])
                for item in language_catalog()
                if item['id'] < limit
            ],
            key=lambda item: item['name'],
        )

    @property
    def keep_alive(self):
        # wl-copy --foreground must keep its owning unit alive while it owns
        # the selection; otherwise systemd would kill the clipboard provider.
        return (
            self.phase != 'idle'
            or bool(self.clipboards)
            or self.notification.busy
            or self.open_microphone_controls
        )

    def snapshot(self):
        return dict(
            phase=self.phase,
            fileOutputs=['clipboard', 'srt'],
            jobId=self.job.get('id', ''),
            source=self.job.get('source', ''),
            output=self.job.get('output', 'clipboard'),
            result=dict(self.result),
            options=dict(self.options),
            modelReady=self.model_ready(),
            models=[
                dict(
                    id=key,
                    name=meta['name'],
                    size=meta['size'],
                    installed=self.model_ready(key),
                )
                for key, meta in MODELS.items()
            ],
            languages=self.languages(),
            allLanguages=self.languages('large-v3'),
            progress=self.progress,
            elapsed=int(time.monotonic() - self.since)
            if self.phase == 'recording'
            else 0,
            error=self.error,
            message=self.message,
            folder=str(self.folder),
            lastAudio=self.last_audio,
            openMicrophoneControls=self.open_microphone_controls,
        )

    def request(self, request):
        operation = request.get('op', '').removeprefix('speech-')
        if operation == 'context':
            self.paste_blocked = request.get('blocked') is not False
        elif operation == 'cancel':
            if not request.get('jobId') or request['jobId'] == self.job.get('id'):
                self.cancel()
        elif operation == 'clear-error':
            self.error = ''
        elif operation == 'controls-opened':
            self.open_microphone_controls = False
        elif operation == 'resume':
            if self.phase != 'microphone-approved' or time.monotonic() >= self.deadline:
                raise ValueError(
                    'The microphone request expired. Start transcription again.'
                )
            try:
                self.start_microphone(approved=True)
            except Exception:
                self.cleanup()
                raise
        elif operation == 'stop':
            if self.phase == 'recording':
                self.process.send_signal(signal.SIGINT)
                self.phase = 'stopping'
                self.deadline = time.monotonic() + 5
                self.restore_microphone()
        elif operation in ('option', 'output'):
            if self.phase != 'idle':
                raise ValueError('Finish speech capture before changing its options.')
            if operation == 'output':
                value = request.get('value')
                if value not in ('copy', 'paste', 'audio'):
                    raise ValueError('Unknown speech output.')
                options = dict(
                    self.options,
                    mode='audio' if value == 'audio' else 'transcribe',
                    paste=value == 'paste',
                )
            else:
                key, value = request.get('key'), request.get('value')
                if not self.valid_option(key, value):
                    raise ValueError('Unknown speech option.')
                if key == 'language' and value not in {
                    item['code'] for item in self.languages()
                }:
                    raise ValueError('This language needs a different speech model.')
                options = dict(self.options, **{key: value})
            if options['language'] not in {
                item['code'] for item in self.languages(options['model'])
            }:
                options['language'] = 'auto'
            self.write(self.preference, json.dumps(options) + '\n')
            self.options = options
            self.message = ''
        elif operation in ('start', 'file', 'setup'):
            if self.phase != 'idle':
                raise ValueError('A speech job is already running.')
            job = dict(self.options, file=operation == 'file', id=uuid.uuid4().hex)
            if operation == 'file':
                source = request.get('path')
                output = request.get('output', 'clipboard')
                identifier = request.get('jobId', job['id'])
                if (
                    not isinstance(source, str)
                    or not Path(source).is_absolute()
                    or not Path(source).is_file()
                ):
                    raise ValueError('Choose an existing local audio or video file.')
                if output not in ('clipboard', 'srt'):
                    raise ValueError('Unknown transcription output.')
                if not isinstance(identifier, str) or not re.fullmatch(
                    r'[a-zA-Z0-9-]{1,80}', identifier
                ):
                    raise ValueError('Invalid transcription job identifier.')
                for key in ('model', 'language'):
                    if key in request:
                        if not self.valid_option(key, request[key]):
                            raise ValueError('Unknown speech option.')
                        job[key] = request[key]
                if job['language'] not in {
                    item['code'] for item in self.languages(job['model'])
                }:
                    raise ValueError('This language needs a different speech model.')
                source = Path(source).resolve()
                target = source.with_suffix('.srt')
                if output == 'srt' and os.path.lexists(target):
                    raise ValueError(f'Subtitles already exist: {target.name}')
                stat = source.stat()
                job.update(
                    id=identifier,
                    source=str(source),
                    output=output,
                    target=str(target),
                    identity=(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns),
                )
            if operation == 'file' or job['mode'] == 'transcribe':
                if not shutil.which('whisper-cli'):
                    raise ValueError('Install whisper-cpp to enable transcription.')
                if operation == 'start' and not self.model_ready(job['model']):
                    raise ValueError('Download the speech model before transcribing.')
            self.error = self.message = ''
            self.result = {}
            self.mute_restore_failed = False
            self.directory.mkdir(parents=True, exist_ok=True)
            self.temporary = tempfile.TemporaryDirectory(
                prefix='speech-', dir=self.directory
            )
            self.path = Path(self.temporary.name)
            self.job = job
            if operation == 'setup' or (
                operation == 'file' and not self.model_ready(job['model'])
            ):
                self.download_model()
                return
            if operation == 'file':
                self.decode_file()
            else:
                try:
                    self.target = active_window()
                    self.start_microphone()
                except Exception:
                    self.cleanup()
                    raise
        else:
            raise ValueError('Unknown speech command.')

    def download_model(self):
        self.progress = -1
        self.notified_progress = -1
        name = MODELS[self.job['model']]['name']
        self.notification.update(f'Downloading {name}', 'Preparing model download…')
        self.spawn(
            [
                'voxtype',
                '--config',
                str(self.config),
                'setup',
                '--download',
                '--model',
                self.job['model'],
                '--progress-format',
                'json',
            ],
            'preparing',
        )

    def decode_file(self):
        self.notification.update('Reading media…', self.job['source'])
        self.spawn(
            [
                'ffmpeg',
                '-nostdin',
                '-v',
                'error',
                '-y',
                '-i',
                self.job['source'],
                '-map',
                '0:a:0',
                '-vn',
                '-t',
                str(MEDIA_LIMIT + 1),
                '-ar',
                '16000',
                '-ac',
                '1',
                '-c:a',
                'pcm_s16le',
                str(self.path / 'audio.wav'),
            ],
            'converting',
        )

    def save_subtitles(self):
        source = Path(self.job['source'])
        stat = source.stat()
        if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != self.job[
            'identity'
        ]:
            raise ValueError('The source changed during transcription. Try again.')
        transcript = self.path / 'transcript.srt'
        if not transcript.read_text().strip():
            self.complete('No speech detected.')
            return
        target = Path(self.job['target'])
        # Stage on the destination filesystem; link publishes without clobbering
        # even a subtitle file created while recognition was running.
        with tempfile.TemporaryDirectory(
            prefix='.subtitles-', dir=target.parent
        ) as folder:
            staged = Path(folder) / target.name
            with staged.open('xb') as output, transcript.open('rb') as data:
                os.chmod(staged, 0o600)
                shutil.copyfileobj(data, output)
            os.link(staged, target)
        self.result = dict(id=self.job['id'], status='saved', path=str(target))
        self.complete('Subtitles saved.', str(target))

    @staticmethod
    def microphone_identity(source):
        properties = source.get('properties', {})
        return (
            source['name'],
            source['index'],
            properties.get('object.serial'),
            properties.get('device.serial'),
        )

    def start_microphone(self, approved=False):
        try:
            source = self.microphone()
        except (OSError, ValueError, subprocess.SubprocessError):
            self.phase = 'microphone-unavailable'
            self.deadline = time.monotonic() + 35
            self.notification.update(
                'Microphone unavailable',
                'Enable or connect a microphone, then try again.',
                finished=True,
                action=('controls', 'Open microphone controls'),
            )
            return
        if approved:
            if (
                not self.prompt_source
                or self.microphone_identity(source) != self.prompt_source
            ):
                raise ValueError('The microphone changed. Start transcription again.')
            if source.get('mute'):
                # Remember ownership before writing: a failing command may
                # still have changed the source before reporting its error.
                self.restore_source = (source['name'], self.microphone_identity(source))
                try:
                    self.mute_microphone(source, False)
                    current = self.microphone(source['name'])
                    if self.microphone_identity(current) != self.microphone_identity(
                        source
                    ) or current.get('mute'):
                        raise ValueError('The microphone could not be unmuted.')
                except (OSError, ValueError, subprocess.SubprocessError):
                    self.cleanup()
                    self.phase = 'microphone-unavailable'
                    self.deadline = time.monotonic() + 35
                    self.notification.update(
                        'Microphone could not be muted'
                        if self.mute_restore_failed
                        else 'Microphone unavailable',
                        'Check microphone controls to restore mute.'
                        if self.mute_restore_failed
                        else 'Could not unmute the microphone. Check its controls or hardware mute switch.',
                        finished=True,
                        action=('controls', 'Open microphone controls'),
                    )
                    return
        elif source.get('mute'):
            self.prompt_source = self.microphone_identity(source)
            self.phase = 'microphone-muted'
            self.deadline = time.monotonic() + 35
            label = (
                'Unmute and record'
                if self.job['mode'] == 'audio'
                else 'Unmute and transcribe'
            )
            self.notification.update(
                'Microphone is muted',
                'It will be muted again when recording stops.',
                finished=True,
                action=('unmute', label),
            )
            return
        self.prompt_source = None
        self.spawn(
            [
                'pw-record',
                '--target=' + source['name'],
                '--rate=16000',
                '--channels=1',
                '--format=s16',
                str(self.path / 'audio.wav'),
            ],
            'recording',
        )
        self.since = time.monotonic()

    def restore_microphone(self):
        source, self.restore_source = self.restore_source, None
        if source is None:
            return
        try:
            current = self.microphone(source[0])
        except ValueError:
            return  # The selected source was disconnected or disabled.
        except (OSError, subprocess.SubprocessError):
            current = None
        try:
            if current is None:
                raise ValueError('Could not read microphone state.')
            if self.microphone_identity(current) != source[1]:
                return  # Never change a replacement device with a reused name.
            if not current.get('mute'):
                self.mute_microphone(current, True)
                current = self.microphone(source[0])
                if self.microphone_identity(current) == source[1] and not current.get(
                    'mute'
                ):
                    raise ValueError('The microphone is still unmuted.')
        except (OSError, ValueError, subprocess.SubprocessError):
            self.mute_restore_failed = True
            self.notification.update(
                'Microphone could not be muted',
                'Check microphone controls to restore mute.',
                finished=True,
                action=('controls', 'Open microphone controls'),
            )

    def spawn(self, command, phase):
        self.log_path = self.path / 'job.log'
        self.log = self.log_path.open('w')
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=self.log,
                stderr=self.log,
                start_new_session=True,
            )
        except OSError:
            self.log.close()
            self.log = None
            self.cleanup()
            raise
        self.phase = phase
        # File decoding and inference are bounded separately from recording.
        self.deadline = time.monotonic() + (
            1800
            if phase == 'preparing'
            else 24 * 60 * 60
            if self.job.get('file')
            else 900
        )

    def audio_duration(self):
        try:
            with wave.open(str(self.path / 'audio.wav')) as audio:
                if (
                    audio.getnchannels(),
                    audio.getsampwidth(),
                    audio.getframerate(),
                ) != (1, 2, 16000):
                    raise ValueError('The audio recording has an unexpected format.')
                frames = audio.getnframes()
                if frames:
                    audio.setpos(frames - 1)
                    if len(audio.readframes(1)) != 2:
                        raise ValueError(
                            'The audio recording is incomplete. Try again.'
                        )
                return frames / audio.getframerate()
        except (OSError, EOFError, wave.Error) as error:
            raise ValueError('Could not read the recorded audio. Try again.') from error

    def transcribe(self):
        duration = self.audio_duration()
        limit = MEDIA_LIMIT if self.job.get('file') else FILE_LIMIT
        if duration > limit:
            raise ValueError(
                f'Choose media no longer than {limit // 3600} hours.'
                if self.job.get('file')
                else 'Choose a recording no longer than 30 minutes.'
            )
        if duration < 0.2:
            self.complete(
                'No speech detected.', 'Try speaking louder or check your microphone.'
            )
            return
        if self.job.get('file'):
            self.notification.update(
                'Generating subtitles…'
                if self.job.get('output') == 'srt'
                else 'Transcribing media…',
                self.job['source'],
            )
        self.spawn(
            [
                'whisper-cli',
                '-m',
                str(self.model_path(self.job['model'])),
                '-l',
                self.job['language'],
                '-f',
                str(self.path / 'audio.wav'),
                '-osrt' if self.job.get('output') == 'srt' else '-otxt',
                '-of',
                str(self.path / 'transcript'),
                '-np',
                '-t',
                str(min(8, os.cpu_count() or 1)),
            ],
            'transcribing',
        )

    def save_audio(self):
        self.audio_duration()
        self.folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
        destination = self.folder / f'Voice_{stamp}.wav'
        # copyfile also works when XDG Music lives on another filesystem.
        with (
            destination.open('xb') as output,
            (self.path / 'audio.wav').open('rb') as source,
        ):
            shutil.copyfileobj(source, output)
        self.last_audio = str(destination)
        self.complete('Audio saved.', str(destination))

    def copy_transcript(self):
        self.text = (self.path / 'transcript.txt').read_text().strip()
        if not self.text:
            self.complete(
                'No speech detected.', 'Try speaking louder or check your microphone.'
            )
            return
        # Feeding a regular file avoids a blocking pipe write in the control loop.
        with (self.path / 'transcript.txt').open('rb') as source:
            self.clipboard = subprocess.Popen(
                ['wl-copy', '--foreground', '--type', 'text/plain;charset=utf-8'],
                stdin=source,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        self.clipboards.append(self.clipboard)
        self.phase = 'delivering'
        self.deadline = time.monotonic() + 0.3

    def tick(self):
        selected = self.notification.tick()
        if selected == 'controls':
            self.open_microphone_controls = True
            self.controls_deadline = time.monotonic() + 10
            if self.phase == 'microphone-unavailable':
                self.cleanup()
        if self.open_microphone_controls and time.monotonic() >= self.controls_deadline:
            self.open_microphone_controls = False
        if self.phase in ('microphone-muted', 'microphone-unavailable'):
            if selected == 'unmute' and self.phase == 'microphone-muted':
                self.phase = 'microphone-approved'
                self.deadline = time.monotonic() + 10
            elif not self.notification.busy or time.monotonic() >= self.deadline:
                self.cancel()
            return
        if self.phase == 'microphone-approved':
            if time.monotonic() >= self.deadline:
                self.cancel()
            return
        self.clipboards = [child for child in self.clipboards if child.poll() is None]
        if self.phase == 'delivering':
            if self.clipboard.poll() is not None:
                self.fail('Could not copy the transcript to the clipboard.')
                self.cleanup()
            elif time.monotonic() >= self.deadline:
                pasted = (
                    self.job['paste']
                    and not self.job['file']
                    and not self.paste_blocked
                    and paste_into(self.target)
                )
                self.message = 'Transcript pasted.' if pasted else 'Transcript copied.'
                detail = '' if pasted else 'Ready to paste from the clipboard.'
                if self.job['paste'] and not self.job['file'] and not pasted:
                    detail = (
                        'Automatic paste skipped. Paste from the clipboard when ready.'
                    )
                self.complete(self.message, detail)
            return
        if not self.process:
            return
        if self.phase == 'recording':
            limit = FILE_LIMIT if self.job['mode'] == 'audio' else 120
            if time.monotonic() - self.since >= limit:
                self.request({'op': 'speech-stop'})
        if self.phase == 'preparing':
            for line in self.log_path.read_text(errors='replace')[-65536:].splitlines():
                try:
                    event = json.loads(line)
                    if event.get('event') == 'progress':
                        pct = event.get('pct')
                        self.progress = pct if type(pct) in (float, int) else -1
                except ValueError:
                    pass
            progress = int(self.progress) if self.progress >= 0 else -1
            if progress != self.notified_progress:
                self.notified_progress = progress
                name = MODELS[self.job['model']]['name']
                body = f'{progress}% downloaded' if progress >= 0 else 'Downloading…'
                self.notification.update(f'Downloading {name}', body, progress)
        code = self.process.poll()
        if code is None:
            if self.phase != 'recording' and time.monotonic() >= self.deadline:
                self.fail('The speech job took too long and was stopped.')
                self.cancel()
            return
        self.process = None
        self.log.close()
        self.log = None
        self.restore_microphone()
        try:
            phase = self.phase
            detail = self.log_path.read_text(errors='replace')[-2000:].strip()
            # pw-record handles SIGINT, finalizes its WAV and exits 1 rather
            # than dying from the signal. Only accept that status after our
            # stop request, without diagnostics; the WAV is validated below.
            stopped = phase == 'stopping' and (
                code == -signal.SIGINT or (code == 1 and not detail)
            )
            if code != 0 and not stopped:
                if phase == 'transcribing':
                    # Engine output can contain recognized words. Keep it out
                    # of notifications and control-socket error snapshots.
                    raise ValueError(
                        'The speech recognition process failed. Try recording again.'
                    )
                raise ValueError(
                    detail
                    or {
                        'recording': 'The microphone recording stopped unexpectedly.',
                        'stopping': 'Could not finish the microphone recording.',
                        'converting': 'Could not read the audio file.',
                        'preparing': 'The speech model download failed.',
                    }.get(phase, 'Speech capture failed.')
                )
            if phase == 'preparing':
                if not self.model_ready(self.job['model']):
                    raise ValueError('The speech model download did not complete.')
                if self.job.get('file'):
                    self.decode_file()
                    return
                name = MODELS[self.job['model']]['name']
                self.message = f'{name} ready.'
                self.notification.update(
                    self.message, 'Ready for local transcription.', 100, finished=True
                )
                self.cleanup()
            elif phase in ('recording', 'stopping') and self.job['mode'] == 'audio':
                self.save_audio()
            elif phase in ('recording', 'stopping', 'converting'):
                self.transcribe()
            elif phase == 'transcribing':
                if self.job.get('output') == 'srt':
                    self.save_subtitles()
                else:
                    self.copy_transcript()
        except (OSError, ValueError, EOFError, wave.Error) as error:
            self.fail(str(error))
            self.cleanup()

    def fail(self, message, title=None, affect_job=True):
        self.error = message
        if affect_job and self.job.get('file') and self.phase != 'idle':
            self.result = dict(id=self.job['id'], status='error', error=message)
        if self.mute_restore_failed:
            self.notification.update(
                'Microphone could not be muted',
                message + ' Check microphone controls to restore mute.',
                finished=True,
                action=('controls', 'Open microphone controls'),
            )
            return
        self.notification.update(
            title
            or (
                'Speech model download failed'
                if self.phase == 'preparing'
                else 'Speech capture failed'
            ),
            message,
            finished=True,
        )

    def complete(self, message, detail=''):
        if self.job.get('file') and not self.result:
            self.result = dict(id=self.job['id'], status='done', message=message)
        self.message = message
        if self.mute_restore_failed:
            self.notification.update(
                'Microphone could not be muted',
                message + ' Check microphone controls to restore mute.',
                finished=True,
                action=('controls', 'Open microphone controls'),
            )
        else:
            self.notification.update(message, detail, finished=True)
        self.cleanup()

    def cleanup(self):
        self.restore_microphone()
        self.prompt_source = None
        if self.temporary:
            self.temporary.cleanup()
            self.temporary = None
        self.phase = 'idle'

    def cancel(self):
        if self.job.get('file') and self.phase != 'idle' and not self.result:
            self.result = dict(
                id=self.job['id'], status='cancelled', message='Cancelled.'
            )
        if self.phase.startswith('microphone-'):
            self.notification.cancel_prompt()
        if self.phase == 'preparing' and not self.error:
            self.notification.update(
                'Speech model download cancelled',
                'You can resume the download later.',
                finished=True,
            )
        if self.process:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
            self.process = None
        if self.log:
            self.log.close()
            self.log = None
        self.cleanup()

    def close(self):
        if self.phase == 'recording' and self.job['mode'] == 'audio':
            self.request({'op': 'speech-stop'})
            try:
                self.process.wait(timeout=5)
                self.tick()
            except subprocess.TimeoutExpired:
                pass
        self.cancel()
        self.notification.close()
        for child in self.clipboards:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
