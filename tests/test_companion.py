"""Desktop companion: speech and agent helper protocol, and the app's state machine."""

import contextlib
import http.server
import json
import math
import os
from pathlib import Path
import random
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import support

COMPANION = support.DESKTOP / 'companion'
helper = support.load('desktop_companion', COMPANION / 'companion.py')


def pcm(samples):
    return struct.pack(f'<{len(samples)}h', *samples)


def tone(seconds, rate=24000, amplitude=8000, frequency=220):
    return [
        int(amplitude * math.sin(2 * math.pi * frequency * i / rate))
        for i in range(int(seconds * rate))
    ]


class HelperTextTests(unittest.TestCase):
    def test_stream_can_queue_another_line_while_synthesis_waits(self):
        started = threading.Event()
        release = threading.Event()
        lines = []

        class SlowOutput:
            def say(self, text):
                started.set()
                if not release.wait(3):
                    raise AssertionError('The chat reader was blocked by synthesis.')
                lines.append(text)

            def finish(self):
                pass

        speaker = helper.Speaker(SlowOutput(), 'all')
        try:
            speaker.say('First.')
            self.assertTrue(started.wait(1))
            speaker.say('Second.')
            self.assertFalse(lines)
        finally:
            release.set()
            speaker.finish()
        self.assertEqual(lines, ['First.', 'Second.'])

    def test_transcription_falls_back_when_lemonade_model_lookup_fails(self):
        path = Path('question.wav')
        with (
            mock.patch.object(helper, 'settings', return_value={'language': 'en'}),
            mock.patch.object(helper, 'transcriber', side_effect=OSError('offline')),
            mock.patch.object(helper, 'whisper_cli', return_value='[NOISE] Hello.'),
            mock.patch.object(helper, 'emit'),
        ):
            self.assertEqual(helper.transcribe(path, 'http://localhost'), 'Hello.')
            helper.whisper_cli.assert_called_once_with(path, 'en')

    def test_streamed_text_becomes_clean_sentences_as_they_end(self):
        chunks = ['Hi! I am **Pip**. Bees', ' make honey 🍯 for winter.\n- Wow', 'ee']
        self.assertEqual(
            list(helper.sentences(chunks)),
            ['Hi! I am Pip.', 'Bees make honey for winter.', 'Wowee'],
        )

    def test_mouth_opens_for_voiced_sound_less_for_hiss_and_not_for_silence(self):
        rate = 24000
        rng = random.Random(4)
        voiced = tone(0.5, rate)
        level = (sum(x * x for x in voiced) / len(voiced)) ** 0.5
        hiss = [int(rng.gauss(0, level)) for _ in range(rate // 2)]
        frames = helper.envelope(pcm([0] * (rate // 2) + voiced + hiss), rate)
        third = len(frames) // 3
        silence = frames[:third]
        vowel = frames[third : 2 * third]
        fricative = frames[2 * third :]
        self.assertEqual(max(silence), 0)
        self.assertGreater(min(vowel[1:-1]), 0.8)
        self.assertLess(max(fricative[1:-1]), min(vowel[1:-1]) * 0.6)
        self.assertEqual(len(frames), 45)
        rounded = helper.roundness('oo ee', 10)
        self.assertEqual(len(rounded), 10)
        self.assertGreater(sum(rounded[:5]), sum(rounded[5:]))

    def test_summary_speaks_one_paragraph_per_round_and_keeps_the_rest_as_details(self):
        said = []

        class Output:
            def say(self, text):
                said.append(text)

            def finish(self):
                pass

        speaker = helper.Speaker(Output(), 'summary')
        speaker.feed("I'll set it now.")
        speaker.tools = True
        speaker.feed(
            '\n\nDone! Your tea timer is running.\n\n- one\n- two\n```\ncode\n```\n'
        )
        speaker.finish()
        self.assertEqual(said, ["I'll set it now.", 'Done! Your tea timer is running.'])
        self.assertIn('- two', speaker.details)

        said.clear()
        speaker = helper.Speaker(Output(), 'all')
        speaker.feed('First line here.\n```\nhidden code\n```\nAnd one more thing!')
        speaker.finish()
        self.assertEqual(said, ['First line here.', 'And one more thing!'])

    def test_memory_is_a_plain_file_with_deduplicated_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = Path(directory) / 'companion/memory.md'
            with mock.patch.object(helper, 'MEMORY', memory):
                helper.remember('Likes **green** 🌿')
                helper.remember('likes green')
                helper.remember('Has a cat called Momo')
                self.assertEqual(
                    helper.memory(), ['Likes green', 'Has a cat called Momo']
                )
                self.assertEqual(helper.forget('cat'), {'forgotten': 1})
                self.assertIn('- Likes green\n', memory.read_text())
                with mock.patch.object(
                    helper, 'settings', return_value={'name': 'Fern'}
                ):
                    text = helper.instructions(helper.BEHAVIORS['friend'])
        self.assertIn('You are Fern', text)
        self.assertIn('- Likes green', text)
        self.assertIn('call remember', text)


def text_stream(*parts):
    return [{'choices': [{'delta': {'content': part}}]} for part in parts] + [
        {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}
    ]


def tool_stream(name, arguments):
    call = {
        'index': 0,
        'id': 'call_1',
        'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(arguments)},
    }
    return [
        {'choices': [{'delta': {'tool_calls': [call]}}]},
        {'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]},
    ]


@contextlib.contextmanager
def fake_lemonade(script=(), tts=True):
    """A loopback Lemonade: status, models, scripted chat rounds, speech, transcription."""
    seen = []
    rounds = list(script)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def answer(self):
            body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            path = self.path.split('?')[0]
            try:
                seen.append((path, json.loads(body) if body else None))
            except ValueError:
                seen.append((path, body))
            if path in ('/v1/health', '/api/v1/health'):
                self.reply({'status': 'ok', 'all_models_loaded': []})
            elif path == '/v1/models':
                rows = [
                    dict(
                        id='Chat',
                        labels=['chat', 'tool-calling', 'vision'],
                        downloaded=True,
                        recipe='llamacpp',
                    ),
                    dict(
                        id='Second', labels=['chat'], downloaded=True, recipe='llamacpp'
                    ),
                    dict(id='Remote', labels=['chat'], downloaded=True, recipe='cloud'),
                    dict(
                        id='Available',
                        labels=['chat'],
                        downloaded=False,
                        recipe='llamacpp',
                    ),
                    dict(
                        id='kokoro-v1', labels=['tts'], downloaded=tts, recipe='kokoro'
                    ),
                    dict(
                        id='Whisper-Small',
                        labels=['transcription'],
                        downloaded=True,
                        recipe='whispercpp',
                    ),
                ]
                self.reply({'data': rows})
            elif path in ('/v1/downloads', '/v1/load'):
                self.reply([] if path == '/v1/downloads' else {'status': 'ok'})
            elif path.endswith('/options'):
                self.reply({'resolved_ctx_size': 16384})
            elif path == '/v1/chat/completions':
                chunks = rounds.pop(0) if rounds else text_stream('Okay.')
                data = b''.join(
                    b'data: ' + json.dumps(chunk).encode() + b'\n\n' for chunk in chunks
                )
                self.reply(data + b'data: [DONE]\n\n', 'text/event-stream')
            elif path == '/v1/audio/speech':
                self.reply(
                    pcm(tone(0.2)), 'audio/l16;rate=24000;endianness=little-endian'
                )
            elif path == '/v1/audio/transcriptions':
                self.reply({'text': ' [MUSIC] What do bees eat? '})
            else:
                self.reply({'error': 'missing'}, status=404)

        def reply(self, value, kind='application/json', status=200):
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = answer

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1], seen
    finally:
        server.shutdown()
        server.server_close()


RECORDER = r"""#!/usr/bin/env python3
import math, os, signal, sys, time
log = os.path.join(os.environ['STUB_LOG'], 'pw-record')
def stopped(*_):
    open(log, 'a').write('stopped\n')
    os._exit(0)
signal.signal(signal.SIGTERM, stopped)
signal.signal(signal.SIGINT, stopped)
open(log, 'a').write('started\n')
mode = os.environ.get('STUB_AUDIO', 'speech')
if mode == 'error':
    sys.exit('No default audio source')
def tone(seconds, amplitude):
    return b''.join(
        int(amplitude * math.sin(2 * math.pi * 220 * i / 16000)).to_bytes(2, 'little', signed=True)
        for i in range(int(seconds * 16000))
    )
out = sys.stdout.buffer
if mode == 'speech':
    out.write(tone(0.5, 60) + tone(1.0, 8000) + tone(1.2, 60))
elif mode == 'immediate':
    out.write(tone(0.7, 360) + tone(1.2, 60))
elif mode == 'short':
    out.write(tone(0.1, 60))
out.flush()
while True:
    if mode == 'quiet':
        out.write(tone(0.1, 60))
        out.flush()
    time.sleep(0.1)
"""
STUBS = {
    # The user unit is active, so the helper never starts or targets a system one.
    'systemctl': """#!/bin/sh
echo "$@" >> "$STUB_LOG/systemctl"
case "$*" in
  *show*--user*|--user*show*) printf 'LoadState=loaded\\nActiveState=%s\\n' "${LEMOND_STATE:-active}" ;;
  *show*) printf 'LoadState=loaded\\nActiveState=inactive\\n' ;;
  *start*) echo 'start refused' >&2; exit 1 ;;
esac
""",
    'pw-record': RECORDER,
    'pw-play': """#!/bin/sh
for last; do :; done
echo "$@" >> "$STUB_LOG/pw-play"
head -c 4 "$last" >> "$STUB_LOG/pw-play-header"
""",
}


class HelperProcessTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.bin = self.root / 'bin'
        self.log = self.root / 'log'
        self.config = self.root / 'config/quickshell/desktop'
        for path in (self.bin, self.log, self.root / 'runtime', self.config):
            path.mkdir(parents=True)
        for name, text in STUBS.items():
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        (self.config / 'speech.json').write_text(json.dumps({'language': 'en'}))
        (self.config / 'companion.json').write_text(
            json.dumps({'name': 'Fern', 'voice': 'af_sky'})
        )

    def start(self, request, port, **extra):
        (self.root / 'config/lemonade').mkdir(parents=True, exist_ok=True)
        (self.root / 'config/lemonade/config.json').write_text(
            json.dumps({'port': port})
        )
        env = {
            **os.environ,
            'PATH': f'{self.bin}{os.pathsep}{os.environ["PATH"]}',
            'XDG_CONFIG_HOME': str(self.root / 'config'),
            'XDG_DATA_HOME': str(self.root / 'data'),
            'XDG_RUNTIME_DIR': str(self.root / 'runtime'),
            'STUB_LOG': str(self.log),
            'PIPEWIRE_REMOTE': 'dotfiles-tests-unavailable',
            **extra,
        }
        for name in ('LEMONADE_API_KEY', 'LEMONADE_ADMIN_API_KEY'):
            env.pop(name, None)
        process = subprocess.Popen(
            [sys.executable, '-B', '-u', str(COMPANION / 'companion.py')],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        self.send(process, request)
        return process

    @staticmethod
    def send(process, value):
        process.stdin.write(
            (value if isinstance(value, str) else json.dumps(value)) + '\n'
        )
        process.stdin.flush()

    def recorder_started(self):
        deadline = time.monotonic() + 5
        log = self.log / 'pw-record'
        while not (log.exists() and 'started' in log.read_text()):
            self.assertLess(time.monotonic(), deadline, 'the recorder never started')
            time.sleep(0.02)

    def events(self, process, intents=None, approve=None, stop_after=None, timeout=30):
        """Collect events, answering intents and approvals like the shell does."""
        events = []
        deadline = time.monotonic() + timeout
        for line in process.stdout:
            event = json.loads(line)
            events.append(event)
            if event['type'] == stop_after:
                self.recorder_started()
                self.send(process, 'stop')
            elif event['type'] == 'intent':
                result = (intents or {}).get(event['name'], {'error': 'unexpected'})
                self.send(process, dict(type='intent', id=event['id'], result=result))
            elif (
                event['type'] == 'tool'
                and event['activity'].get('state') == 'pending_approval'
            ):
                self.send(
                    process,
                    dict(type='approval', id=event['activity']['id'], approved=approve),
                )
            self.assertLess(time.monotonic(), deadline, events)
        process.wait(timeout=5)
        return [event for event in events if event['type'] != 'level']

    def test_hands_free_turn_transcribes_on_the_gpu_runs_a_desktop_tool_and_speaks(
        self,
    ):
        script = [
            tool_stream('media_control', {'action': 'status'}),
            text_stream('Bees love nectar. ', 'They make honey from it!'),
        ]
        with fake_lemonade(script) as (port, seen):
            process = self.start(
                dict(
                    op='turn',
                    listen='auto',
                    behavior='friend',
                    history=[],
                    context={'app': 'Paint'},
                ),
                port,
            )
            events = self.events(process, intents={'media_control': {'playing': False}})
        kinds = [event['type'] for event in events]
        self.assertEqual(
            kinds,
            [
                'listening',
                'transcribing',
                'heard',
                'thinking',
                'action',
                'intent',
                'speech',
                'speech',
                'reply',
                'done',
            ],
            events,
        )
        self.assertEqual(events[2]['text'], 'What do bees eat?')
        self.assertEqual(events[5]['arguments'], {'action': 'status'})
        speeches = [event for event in events if event['type'] == 'speech']
        self.assertEqual(
            [event['text'] for event in speeches],
            ['Bees love nectar.', 'They make honey from it!'],
        )
        self.assertTrue(
            all(len(event['round']) == len(event['envelope']) for event in speeches)
        )
        self.assertIn('started\nstopped', (self.log / 'pw-record').read_text())
        transcription = next(
            body for path, body in seen if path == '/v1/audio/transcriptions'
        )
        self.assertIn(b'Whisper-Small', transcription)
        self.assertIn(b'name="language"\r\n\r\nen', transcription)
        self.assertIn(b'RIFF', transcription)
        chats = [body for path, body in seen if path == '/v1/chat/completions']
        self.assertIn('You are Fern', chats[0]['messages'][0]['content'])
        self.assertNotIn('"Paint"', chats[0]['messages'][0]['content'])
        self.assertIn('play_space_result', chats[0]['messages'][0]['content'])
        self.assertIn('match=keywords', chats[0]['messages'][0]['content'])
        self.assertIn('get_song_lyrics', chats[0]['messages'][0]['content'])
        self.assertNotIn('present_space_results', chats[0]['messages'][0]['content'])
        self.assertIs(chats[0]['enable_thinking'], False)
        offered = {tool['function']['name'] for tool in chats[0]['tools']}
        self.assertTrue(
            {
                'timer',
                'window',
                'agenda',
                'lid_policy',
                'open_app',
                'web_search',
                'search_lyrics',
                'get_song_lyrics',
            }
            <= offered
        )
        self.assertFalse({'run_command', 'write_file', 'read_file'} & offered)
        result = json.loads(chats[1]['messages'][-1]['content'])
        self.assertEqual(result, {'untrusted_tool_result': {'playing': False}})
        speech = [body for path, body in seen if path == '/v1/audio/speech']
        self.assertTrue(all(body['voice'] == 'af_sky' for body in speech))
        self.assertEqual((self.log / 'pw-play-header').read_text(), 'RIFFRIFF')
        self.assertEqual(list((self.root / 'runtime').iterdir()), [])

    def test_assistant_file_changes_wait_for_a_click_and_a_refusal_runs_nothing(self):
        target = self.root / 'note.txt'
        content = ('hello\n' * 850) + 'end of preview'
        script = [
            tool_stream('write_file', {'path': str(target), 'content': content}),
            text_stream('I did not write it.'),
        ]
        with fake_lemonade(script) as (port, seen):
            events = self.events(
                self.start(
                    dict(op='turn', text='Write it', behavior='assistant'), port
                ),
                approve=False,
            )
        states = [
            event['activity']['state'] for event in events if event['type'] == 'tool'
        ]
        self.assertEqual(states, ['pending_approval', 'rejected'])
        pending = next(event for event in events if event['type'] == 'tool')
        self.assertEqual(pending['activity']['arguments']['content'], content)
        self.assertFalse(target.exists())
        self.assertEqual(events[-2]['type'], 'reply', events[-2])

    def test_friend_cannot_reach_tools_its_behaviour_does_not_offer(self):
        script = [
            tool_stream('run_command', {'command': 'touch /tmp/companion-escape'}),
            text_stream('I cannot do that.'),
        ]
        with fake_lemonade(script) as (port, seen):
            events = self.events(
                self.start(dict(op='turn', text='Run it', behavior='friend'), port),
                approve=True,
            )
        self.assertFalse(any(event['type'] == 'tool' for event in events), events)
        chats = [body for path, body in seen if path == '/v1/chat/completions']
        result = json.loads(chats[1]['messages'][-1]['content'])
        self.assertIn('not available', result['untrusted_tool_result']['error'])

    def test_a_remember_call_writes_the_memory_file(self):
        script = [
            tool_stream('remember', {'fact': 'Likes green'}),
            text_stream('Saved!'),
        ]
        with fake_lemonade(script) as (port, _):
            self.events(self.start(dict(op='turn', text='Remember green'), port))
        self.assertIn(
            '- Likes green', (self.root / 'data/companion/memory.md').read_text()
        )

    def test_pip_uses_shared_microphone_status_and_keeps_it_for_handoff(self):
        cli = self.bin / 'qs'
        cli.write_text(
            '#!/usr/bin/env python3\n'
            'import json,os,sys\n'
            'assert os.environ["LC_ALL"] == "C.UTF-8"\n'
            'assert sys.argv[5:7] == ["assistant", "microphone"], sys.argv\n'
            'assert json.loads(sys.argv[7]) == {"action": "status"}\n'
            'mic = dict(id="18", label="Headset", muted=True, active=True, level=45)\n'
            'print(json.dumps(dict(active=mic, inputs=[mic])))\n'
        )
        cli.chmod(0o755)
        script = [
            tool_stream('microphone', {'action': 'status'}),
            text_stream('Your headset is muted.'),
        ]
        with fake_lemonade(script) as (port, seen):
            events = self.events(
                self.start(
                    dict(op='turn', text="Why can't Pip hear me?", behavior='quiet'),
                    port,
                )
            )
        payload = next(body for path, body in seen if path == '/v1/chat/completions')
        self.assertIn(
            'microphone', {tool['function']['name'] for tool in payload['tools']}
        )
        reply = next(event for event in events if event['type'] == 'reply')
        self.assertEqual(reply['text'], 'Your headset is muted.')
        self.assertEqual(reply['results'][0]['result']['active']['label'], 'Headset')
        self.assertTrue(reply['results'][0]['result']['active']['muted'])

    def test_cancelling_while_listening_stops_the_recorder_and_cleans_up(self):
        with fake_lemonade() as (port, _):
            process = self.start(
                dict(op='turn', listen='auto'), port, STUB_AUDIO='quiet'
            )
            self.assertEqual(json.loads(process.stdout.readline())['type'], 'listening')
            self.recorder_started()
            process.send_signal(signal.SIGTERM)
            events = self.events(process)
        self.assertEqual(events, [{'type': 'cancelled'}])
        self.assertEqual(process.returncode, 0)
        deadline = time.monotonic() + 3
        while 'stopped' not in (self.log / 'pw-record').read_text():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        self.assertEqual(list((self.root / 'runtime').iterdir()), [])

    def test_held_recordings_end_on_stop_and_silence_ends_hands_free_ones(self):
        with fake_lemonade() as (port, seen):
            held = self.events(
                self.start(dict(op='turn', listen='hold'), port, STUB_AUDIO='short'),
                stop_after='listening',
            )
            quiet = self.events(
                self.start(
                    dict(op='turn', listen='auto', followUp=True),
                    port,
                    STUB_AUDIO='quiet',
                ),
                timeout=20,
            )
        self.assertEqual(
            held[-2:], [dict(type='nothing', reason='short'), dict(type='done')]
        )
        self.assertEqual(
            quiet[-2:], [dict(type='nothing', reason='silent'), dict(type='done')]
        )
        self.assertFalse(any(path == '/v1/chat/completions' for path, _ in seen))

    def test_hands_free_detects_immediate_quiet_speech_and_reports_recorder_errors(
        self,
    ):
        with fake_lemonade() as (port, _):
            immediate = self.events(
                self.start(
                    dict(op='turn', listen='auto', behavior='quiet'),
                    port,
                    STUB_AUDIO='immediate',
                )
            )
            broken = self.events(
                self.start(
                    dict(op='turn', listen='auto'),
                    port,
                    STUB_AUDIO='error',
                )
            )
        self.assertIn('heard', [event['type'] for event in immediate])
        self.assertEqual(
            broken[-2],
            dict(
                type='error',
                kind='microphone',
                error='No default audio source',
            ),
        )

    def test_only_downloaded_local_chat_models_are_listed_and_used(self):
        settings = self.config / 'companion.json'
        (self.config / 'assistant.json').write_text(json.dumps({'model': 'Chat'}))
        with fake_lemonade() as (port, seen):
            settings.write_text(json.dumps({'model': 'Available'}))
            models = self.events(self.start(dict(op='models'), port))[0]
            self.assertEqual(
                models,
                dict(
                    type='models',
                    selected='Chat',
                    models=[
                        dict(id='Chat', vision=True),
                        dict(id='Second', vision=False),
                    ],
                ),
            )
            settings.write_text(json.dumps({'model': 'Second'}))
            self.events(
                self.start(dict(op='turn', text='Hello', behavior='quiet'), port)
            )
        self.assertFalse(any(path in ('/v1/load', '/v1/pull') for path, _ in seen))
        payload = next(body for path, body in seen if path == '/v1/chat/completions')
        self.assertEqual(payload['model'], 'Second')

    def test_without_speech_model_lines_are_paced_for_reading_and_nothing_downloads(
        self,
    ):
        with fake_lemonade(tts=False) as (port, seen):
            started = time.monotonic()
            events = self.events(
                self.start(
                    dict(op='say', text='Hello there, friend! Bye for now.'), port
                )
            )
            elapsed = time.monotonic() - started
        self.assertEqual([event['type'] for event in events], ['line', 'line', 'done'])
        self.assertGreaterEqual(
            elapsed, sum(event['duration'] for event in events[:2]) - 0.2
        )
        self.assertFalse(
            any(path in ('/v1/audio/speech', '/v1/pull') for path, _ in seen)
        )

    def test_text_only_requests_show_lines_even_when_a_voice_is_available(self):
        with fake_lemonade() as (port, seen):
            events = self.events(
                self.start(
                    dict(op='say', text='Hello there, friend!', voice=False), port
                )
            )
        self.assertEqual([event['type'] for event in events], ['line', 'done'])
        self.assertFalse(any(path == '/v1/audio/speech' for path, _ in seen))

    def test_unavailable_lemonade_reports_offline_after_trying_the_user_unit(self):
        with fake_lemonade() as (port, _):
            pass
        events = self.events(
            self.start(dict(op='turn', text='Hello?'), port, LEMOND_STATE='inactive')
        )
        self.assertEqual(
            [event['type'] for event in events], ['thinking', 'error', 'done']
        )
        self.assertEqual(events[1]['kind'], 'offline')
        self.assertIn(
            '--user start lemond.service', (self.log / 'systemctl').read_text()
        )


class SpaceResultTests(unittest.TestCase):
    """Pip plays Space results through the shell, like a card's Play button."""

    def test_a_search_ref_reaches_the_shell_as_its_card_payload(self):
        result = {
            'ref': 'space_' + 'a' * 32,
            'kind': 'song',
            'space': 'music',
            'title': '15 Min Flame',
            'playable': True,
            'payload': {'item': {'id': 'track-1', 'title': '15 Min Flame'}},
        }
        album = dict(result, ref='space_' + 'b' * 32, kind='album', playable=False)
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / 'qs'
            stub.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$(dirname "$0")/args"\n'
                '[ "$9" = fail ] && echo "This Space is unavailable."\nexit 0\n'
            )
            stub.chmod(0o755)
            path = {'PATH': f'{directory}{os.pathsep}{os.environ["PATH"]}'}
            results = {result['ref']: result, album['ref']: album}
            with (
                mock.patch.dict(os.environ, path),
                mock.patch.dict(helper.lemonade.SPACE_RESULTS, results, clear=True),
            ):
                played = helper.open_space({'ref': result['ref']})
                args = (Path(directory) / 'args').read_text().splitlines()
                opened = helper.open_space({'ref': album['ref'], 'play': True})
                missing = helper.open_space({'ref': 'space_' + 'c' * 32})
        self.assertEqual(
            played, {'opened': '15 Min Flame', 'space': 'music', 'playing': True}
        )
        self.assertEqual(args[:6], ['ipc', '--path', args[2], 'call', 'spaces', 'open'])
        self.assertTrue(args[2].endswith('quickshell/desktop/shell.qml'))
        self.assertEqual(
            json.loads(args[6]),
            {'space': 'music', 'payload': result['payload'], 'play': True},
        )
        self.assertFalse(opened['playing'])
        self.assertIn('note', opened)
        self.assertIn('search_spaces', missing['error'])

    def test_the_shell_inbox_opens_results_without_provider_commands(self):
        state = """pragma Singleton
import Quickshell
Singleton {
    property var calls: []
    readonly property var entries: [{id: "music"}, {id: "movies"}]
    function open(id, output, payload) {
        calls = calls.concat([{id, output: output?.name ?? "", payload}]);
        return entries.some(entry => entry.id === id);
    }
}
"""
        body = """import QtQuick
import Quickshell
import "ui"
ShellRoot {
    SpaceInbox { id: inbox }
    Timer {
        interval: 50
        running: true
        onTriggered: {
            try {
                const payload = {item: {id: "1", command: "rm -rf ~", nested: [{actions: ["x"], keep: 1}]}};
                const results = [
                    inbox.open(JSON.stringify({space: "music", payload, play: true})),
                    inbox.open(JSON.stringify({space: "nope", payload: {}})),
                    inbox.open("not json"),
                    inbox.open(JSON.stringify({space: "music", payload: [1]})),
                    inbox.open("x".repeat(100000))
                ];
                const call = SpaceState.calls[0];
                const ok = results[0] === "" && results.slice(1).every(text => text !== "")
                    && SpaceState.calls.length === 2 && call.id === "music" && call.output === Quickshell.screens[0].name
                    && call.payload.play === true && !("command" in call.payload.item)
                    && !("actions" in call.payload.item.nested[0]) && call.payload.item.nested[0].keep === 1;
                console.log(ok ? "DISPLAY_PASS" : "DISPLAY_FAIL " + JSON.stringify({results, calls: SpaceState.calls}));
            } catch (error) {
                console.log("DISPLAY_FAIL " + error);
            } finally {
                Qt.quit();
            }
        }
    }
}
"""
        support.run_qml(
            self, body, lambda root: (root / 'ui/SpaceState.qml').write_text(state)
        )


# The helper stand-in follows the real protocol: warm reports capabilities,
# "say" speaks one sentence ("long" keeps speaking until cancelled), a held
# turn logs the line that ends it, and "tool" asks for a timer and an approval.
STUB_HELPER = r"""import json, os, signal, sys, time
request = json.loads(sys.stdin.readline())
log = os.path.join(os.environ['XDG_RUNTIME_DIR'], 'helper.log')
def note(text):
    with open(log, 'a') as handle:
        handle.write(text + '\n')
def stop(*_):
    note('terminated')
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
note(json.dumps(request))
def emit(value):
    print(json.dumps(value), flush=True)
op, text = request.get('op'), request.get('text', '')
if op in ('warm', 'models'):
    emit(dict(type='models', selected='Chat', models=[
        dict(id='Chat', vision=True), dict(id='Second', vision=False),
    ]))
    if op == 'warm':
        emit(dict(type='ready', voice=True, vision=True, model='Chat', transcriber=''))
elif request.get('listen'):
    emit(dict(type='listening'))
    if request.get('followUp'):
        emit(dict(type='listen_wait', seconds=5))
    held = request.get('listen') == 'hold'
    for line in sys.stdin:
        command = line.strip()
        note('stdin:' + command)
        if command == 'hold':
            held = True
        if command == 'stop':
            break
    if not held and request.get('followUp') is False:
        emit(dict(type='reply', question='voice', text='I heard you.'))
    else:
        emit(dict(type='nothing', reason='short'))
elif text == 'tool':
    emit(dict(type='thinking'))
    emit(dict(type='intent', id='i1', name='media_control', arguments={'action': 'status'}))
    note('intent:' + sys.stdin.readline().strip())
    emit(dict(type='tool', activity=dict(id='a1', name='run_command', state='pending_approval', arguments={'command': 'echo hi'})))
    note('approval:' + sys.stdin.readline().strip())
    mic = dict(id='22', label='USB headset', level=50, muted=True, active=True)
    emit(dict(type='reply', id='a' * 32, model='Chat', question='tool', text='Done',
              tool_context=[], results=[
                  dict(name='microphone', args=dict(action='status'), result=dict(active=mic, inputs=[mic])),
                  dict(name='agenda', args=dict(action='today'), result=dict(events=[dict(title='Lunch')])),
                  dict(name='search_spaces', args=dict(kind='movie'), result=dict(items=[
                      dict(title='Film', payload=dict(command='strip it', title=dict(title='Film')))
                  ])),
              ]))
    emit(dict(type='details', text='Done\n\n- one\n- two'))
else:
    emit(dict(type='speech', text=text + '.', envelope=[0.2, 0.9, 0.4] * 40, round=[0] * 120, fps=30, duration=4))
    time.sleep(30 if text == 'long' else 0.6)
emit(dict(type='done'))
"""

SHELL = """import QtQuick
import QtTest
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import "companion"
import "drawers/assistant"
ShellRoot {
    id: root
    Companion { id: companion }
    AssistantInbox {
        id: inbox
        publishPresence: true
        audio: ({
            microphones: () => ({inputs: [], active: null}),
            selectMicrophone: id => ({requested: id === "22"})
        })
        openDrawer: (key, output) => {
            root.lastDrawer = [key, output];
            return true;
        }
    }
    TestCase { id: input; when: false }
    function check(value, message) { if (!value) throw new Error(message); }
    function fake(control) { Hyprland.dispatch("fake:" + JSON.stringify(control)); }
    // A reused FileView can return stale text after reload(); read afresh.
    function helperText() {
        const view = Qt.createQmlObject('import Quickshell.Io; FileView { blockLoading: true; printErrors: false }', root);
        view.path = Quickshell.env("XDG_RUNTIME_DIR") + "/helper.log";
        const text = view.text();
        view.destroy();
        return text;
    }
    function find(item, name) {
        if (!item) return null;
        if (item.objectName === name) return item;
        for (const child of item.children || []) { const found = find(child, name); if (found) return found; }
        return null;
    }
    function part(name) { return find(companion.window.contentItem, name); }
    function click(item) { input.mouseClick(item, item.width / 2, item.height / 2); }
    function desktop(tool, args, context = {}) {
        return JSON.parse(inbox.desktop(JSON.stringify({tool, args, context})));
    }
    readonly property var steps: [
        [() => !!companion.window && companion.selectedChatModel?.vision === true, () => {
            check(companion.window.screen.name === "OUT-1", "wrong output: " + companion.window.screen.name);
            check(companion.behaviorId === "playful", "default behaviour " + companion.behaviorId);
        }],
        // The cursor is up and to the left of the bottom-right corner.
        [() => companion.window.puppet.gaze.x < -0.3 && companion.window.puppet.gaze.y > 0.2, () => {
            check(companion.say("Hello there"), "say was refused");
        }],
        [() => companion.bubbleText === "Hello there." && companion.window.puppet.speaking, () => {}],
        [() => companion.phase === "idle" && companion.lastSpoken === "Hello there.", () => companion.repeat()],
        // Repeating sends what was said, with the behaviour's voice setting.
        [() => helperText().includes('"text": "Hello there.", "start": true, "voice": true') && companion.phase === "idle", () => companion.say("long")],
        [() => companion.phase === "speaking" && companion.bubbleText === "long.", () => {
            const hit = part("companionHitArea");
            input.mouseClick(hit, 72, 120);
        }],
        [() => helperText().includes("terminated"), () => {
            check(companion.phase === "idle", "interrupted phase " + companion.phase);
            check(["Okay!", "Got it."].includes(companion.bubbleText), "bubble " + companion.bubbleText);
            input.mousePress(part("companionHitArea"), 72, 82);
        }],
        // Holding the character listens until release.
        [() => companion.phase === "listening", () => input.mouseRelease(part("companionHitArea"), 72, 82)],
        [() => helperText().includes("stdin:stop") && companion.bubbleText === "Hold me while you talk!", () => {
            check(companion.ask("tool"), "ask was refused");
        }],
        // Desktop intents answer the helper; approvals wait for a click.
        [() => !!companion.approval && !!part("approvalAllow") && part("approvalAllow").visible, () => {
            check(helperText().includes("No music or video player is open"), "intent was not answered: " + helperText());
            click(part("approvalAllow"));
        }],
        [() => helperText().includes('"approved":true') && companion.phase === "idle" && !!companion.details, () => {
            check(companion.history.length === 2, "history " + companion.history.length);
            check(JSON.parse(inbox.microphone('{"action":"status"}')).active === null, "live microphone status did not reach the inbox");
            check(JSON.parse(inbox.microphone('{"action":"select","id":"22"}')).requested, "microphone selection did not reach the inbox");
            check(!!JSON.parse(inbox.microphone('{"action":"select","id":"name"}')).error, "unvalidated input ID");
            check(JSON.parse(inbox.microphone('{"action":"open"}')).opened && root.lastDrawer[0] === "microphone", "microphone drawer was not opened");
            AssistantService.draft = "Existing draft";
            AssistantService.appendUserMessage("Earlier question", []);
            companion.showDetails = true;
        }],
        [() => !!part("continueInAssistant")?.visible, () => click(part("continueInAssistant"))],
        [() => AssistantService.messages.count === 3 && !companion.openingDrawer, () => {
            check(root.lastDrawer.join("/") === "assistant/OUT-1", "handoff opened the wrong drawer or display");
            check(AssistantService.draft === "Existing draft" && AssistantService.messages.get(0).body === "Earlier question", "handoff changed the draft or history");
            check(AssistantService.messages.get(1).body === "tool" && AssistantService.messages.get(2).body === "Done", "handoff lost the exchange");
            const tools = JSON.parse(AssistantService.messages.get(2).toolActivitiesJson);
            check(tools[0].result.active.label === "USB headset" && tools[0].state === "completed", "live microphone result was lost");
            check(tools[1].result.events[0].title === "Lunch", "agenda result was lost");
            check(tools[2].result.items[0].payload.command === undefined, "handoff kept a provider command");
            check(!AssistantService.generating, "handoff sent the prompt again");
            check(inbox.continueFromPip(JSON.stringify(companion.lastReply)) === "" && AssistantService.messages.count === 3, "handoff duplicated the exchange");
            const window = (id, pid, title, monitor) => ({address: id, title, monitor: {name: monitor},
                workspace: {name: "work"}, lastIpcObject: {class: "editor", pid}});
            const editor = window("0xaa01", 20, "A.py", "OUT-1");
            const second = window("0xbb02", 30, "B.py", "OUT-2");
            inbox.desktopActions.compositor = {
                usingLua: true, activeToplevel: second, toplevels: {values: [editor, second]},
                monitors: {values: [{id: 0, name: "OUT-1"}, {id: 1, name: "OUT-2"}]},
                dispatch: script => { root.windowCommand = script; }
            };
            check(desktop("window", {action: "focus", target: "editor"}).candidates.length === 2 && !root.windowCommand, "ambiguous window changed focus");
            const origin = {window: {id: "aa01", app: "editor", pid: 20}};
            check(desktop("window", {action: "move", target: "current", monitor: "other"}, origin).monitor === "OUT-2"
                  && root.windowCommand.includes('address:0xaa01') && root.windowCommand.includes('monitor = "1"'), "move did not target the captured window");
            origin.window.pid = 42;
            check(!!desktop("window", {action: "focus", target: "current"}, origin).error, "a stale captured window was accepted");
            inbox.desktopActions.calendar = {
                clock: () => new Date(2026, 10, 20),
                state: {eventsReady: true, stale: true},
                eventsOn: () => [{summary: "Lunch", all_day: true, date: "2026-11-20", last_date: "2026-11-20"}]
            };
            check(desktop("agenda", {action: "today"}).events[0].title === "Lunch", "calendar did not use its service data");
            inbox.desktopActions.reminders.deliver = () => { root.timerPrompts++; };
            check(desktop("timer", {action: "focus", minutes: 25}).started, "focus did not start");
            root.timerId = desktop("timer", {action: "timer", seconds: 60, label: "Tea"}).id;
            check(desktop("timer", {action: "list"}).timers.length === 2, "timer list was not shared");
        }],
        [() => companion.focusPhase === "focus" && companion.timers.length === 2, () => {
            check(companion.window.puppet.foldLeaves, "Pip did not fold its leaves during focus");
            const reminders = inbox.desktopActions.reminders;
            check(desktop("timer", {action: "stop", id: root.timerId}).stopped, "couldn't stop a shared timer");
            reminders.tick(reminders.entries[0].deadline);
        }],
        [() => companion.focusPhase === "break", () => {
            check(!companion.window.puppet.foldLeaves && root.timerPrompts === 1, "focus did not advance cleanly");
            check(desktop("timer", {action: "stop", kind: "focus"}).stopped, "couldn't stop focus");
            companion.pressTalk();
            companion.releaseTalk();
        }],
        [() => companion.phase === "listening" && helperText().includes('"listen": "auto"'), () => {
            check(companion.handsFree, "tapping should leave hands-free listening active");
            companion.pressTalk();
            companion.releaseTalk();
        }],
        [() => companion.phase === "idle" && companion.history.length === 4, () => {
            root.stamp = Date.now();
            companion.ask("long");
        }],
        [() => Date.now() - root.stamp > 500, () => {
            check(companion.phase === "speaking" && !helperText().includes('"followUp": true'), "follow-up interrupted the typed turn");
            companion.pressTalk();
        }],
        [() => companion.talkHeld, () => {
            check(!companion.handsFree, "holding should disable follow-ups");
            companion.releaseTalk();
        }],
        [() => companion.phase === "idle" && helperText().includes("stdin:hold\\nstdin:stop"), () => {
            input.mouseClick(part("companionHitArea"), 72, 82, Qt.RightButton);
        }],
        [() => companion.window.interactive && helperText().includes('"op": "models"'), () => {
            const menu = input.findChild(companion.window, "companionMenu");
            check(!!menu, "context menu was not created");
            const item = Array.from({length: menu.count}, (_, i) => menu.itemAt(i)).find(item => item.text === "Chat model");
            check(!!item && item.enabled, "chat model selector is missing");
            root.modelMenu = item.subMenu;
            click(item);
        }],
        [() => root.modelMenu?.opened, () => {
            check(companion.window.interactive && root.modelMenu.count === 2, "model menu did not accept input");
            check(root.modelMenu.itemAt(0).marked, "default model was not marked");
            click(root.modelMenu.itemAt(1));
        }],
        [() => !companion.window.interactive && companion.selectedChatModel?.id === "Second", () => {
            companion.pressTalk();
            companion.releaseTalk();
        }],
        [() => companion.recorderOpen && companion.followUps === 0, () => companion.stopListening()],
        [() => companion.recorderOpen && companion.followUpSeconds === 5 && !!part("companionStopCapture")?.visible, () => {
            click(part("companionStopCapture"));
        }],
        [() => companion.phase === "idle" && !companion.recorderOpen, () => {
            check(companion.history.length === 6, "cancelling follow-up changed chat history");
            companion.setBehavior("quiet");
        }],
        [() => companion.settings.behavior === "quiet" && companion.selectedChatModel?.id === "Second", () => {
            const hit = part("companionHitArea");
            input.mousePress(hit, 72, 82);
            for (let step = 1; step <= 4; step++)
                input.mouseMove(hit, 72 - step * 15, 82 - step * 15);
        }],
        // The window follows the compositor's cursor (fixed at 10,80) to the clamped edge.
        [() => companion.dragging && companion.window.marginRight === companion.window.clampRight(10000, false), () => input.mouseRelease(part("companionHitArea"), 12, 22)],
        [() => !companion.dragging && companion.position.right === companion.window.clampRight(10000, false), () => {
            root.stamp = Date.now();
            fake({events: ["screencast>>1,monitor", "screencast>>0,monitor"]});
        }],
        // A screenshot reports a cast for a moment; it must not hide or interrupt.
        [() => Date.now() - root.stamp > 2200, () => {
            check(!!companion.window && companion.shown, "a screenshot hid the companion");
            fake({events: ["screencast>>1,monitor"]});
        }],
        [() => !companion.window && !companion.shown, () => fake({events: ["screencast>>0,monitor"]})],
        [() => !!companion.window, () => { console.log("COMPANION_PASS"); Qt.quit(); }]
    ]
    property var modelMenu: null
    property var lastDrawer: []
    property string windowCommand: ""
    property int timerId: 0
    property int timerPrompts: 0
    property double stamp: 0
    property int step: 0
    property int waits: 0
    Timer { interval: 100; running: true; repeat: true; onTriggered: {
        try {
            if (!root.steps[root.step][0]()) {
                check(++root.waits < 100, "timed out waiting: " + JSON.stringify({
                    phase: companion.phase,
                    bubble: companion.bubbleText,
                    approval: companion.approval,
                    dragging: companion.dragging,
                    margins: [companion.window?.marginRight, companion.window?.marginBottom],
                    cursor: [companion.cursor.x, companion.cursor.y],
                    helper: helperText()
                }));
                return;
            }
            root.steps[root.step][1]();
            root.step++;
            root.waits = 0;
        } catch (error) { console.error("COMPANION_FAIL", root.step, error.message); Qt.quit(); }
    } }
}
"""


@unittest.skipUnless(
    support.QS and shutil.which('dbus-run-session'),
    'Quickshell and a private D-Bus are required',
)
class CompanionAppTests(unittest.TestCase):
    def test_app_tracks_speaks_interrupts_listens_asks_moves_and_hides(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        support.copy_theme_ui(root)
        shutil.copytree(
            COMPANION, root / 'companion', ignore=shutil.ignore_patterns('__pycache__')
        )
        for directory in (
            'drawers/assistant',
            'drawers/audio',
            'drawers/weather',
            'drawers/events',
            'drawers/notifications',
            'launcher',
            'icons',
            'spaces',
        ):
            shutil.copytree(
                support.DESKTOP / directory,
                root / directory,
                ignore=shutil.ignore_patterns('__pycache__'),
            )
        (root / 'drawers/weather/backend.py').write_text(
            'import json; print(json.dumps({"weather": {"current": {"code": 61, "feelsLike": 3, "isDay": True}}}))'
        )
        (root / 'companion/companion.py').write_text(STUB_HELPER)
        support.floating_window(root / 'companion/CompanionWindow.qml')
        (root / 'shell.qml').write_text(SHELL)
        (root / 'screens.json').write_text(
            json.dumps(
                {'screens': [dict(name='OUT-1', x=0, y=0, width=1280, height=720)]}
            )
        )
        config = root / 'config/quickshell/desktop'
        config.mkdir(parents=True)
        (config / 'theme-mode').write_text('dark\n')
        runtime = root / 'runtime'
        runtime.mkdir(mode=0o700)
        hyprland = support.FakeHyprland(
            runtime / 'hypr/test',
            clients=[],
            workspaces=[
                dict(
                    id=1,
                    name='1',
                    monitor='OUT-1',
                    monitorID=0,
                    windows=0,
                    hasfullscreen=False,
                )
            ],
            monitors=[
                dict(
                    id=0,
                    name='OUT-1',
                    description='OUT-1',
                    x=0,
                    y=0,
                    width=1280,
                    height=720,
                    scale=1,
                    activeWorkspace={'id': 1, 'name': '1'},
                    focused=True,
                )
            ],
        )
        hyprland.state['cursorpos'] = {'x': 10, 'y': 80}
        env = {
            **os.environ,
            'QT_QPA_PLATFORM': f'offscreen:configfile={root / "screens.json"}',
            'HYPRLAND_INSTANCE_SIGNATURE': 'test',
            'XDG_RUNTIME_DIR': str(runtime),
            'XDG_CONFIG_HOME': str(root / 'config'),
            'XDG_DATA_HOME': str(root / 'data'),
            'XDG_STATE_HOME': str(root / 'state'),
            'XDG_CACHE_HOME': str(root / 'cache'),
            'PIPEWIRE_REMOTE': 'dotfiles-tests-unavailable',
        }
        env.pop('WAYLAND_DISPLAY', None)
        env.pop('COMPANION_BEHAVIOR', None)
        try:
            result = subprocess.run(
                [
                    *support.private_bus(root),
                    support.QS,
                    '--no-color',
                    '-p',
                    str(root / 'shell.qml'),
                ],
                env=env,
                text=True,
                capture_output=True,
                timeout=90,
            )
        finally:
            hyprland.close()
        log = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, log)
        self.assertIn('COMPANION_PASS', log)
        for error in ('COMPANION_FAIL', 'TypeError', 'ReferenceError', 'Binding loop'):
            self.assertNotIn(error, log)
        saved = json.loads((config / 'companion.json').read_text())
        self.assertEqual(saved['behavior'], 'quiet')
        self.assertEqual(saved['model'], 'Second')
        cursor = [
            request for _, request in hyprland.requests if request == 'j/cursorpos'
        ]
        self.assertGreater(len(cursor), 2)


if __name__ == '__main__':
    unittest.main()
