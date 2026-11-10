"""Speech capture without a real microphone, clipboard, model or compositor."""

import copy
import json
import os
from pathlib import Path
import socket
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from unittest.mock import Mock, patch

import support

speech = support.load('capture_speech', support.DESKTOP / 'drawers/capture/speech.py')


class SpeechTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        binary = self.root / 'bin'
        binary.mkdir()
        script = binary / 'fake'
        script.write_text(
            f'#!{sys.executable}\n'
            + """import json, os, signal, sys, time, wave
from pathlib import Path
root=Path(os.environ['SPEECH_FIXTURE'])
name=Path(sys.argv[0]).name
args=sys.argv[1:]
def wav(path):
    with wave.open(str(path),'w') as audio:
        audio.setparams((1,2,16000,0,'NONE','not compressed'))
        audio.writeframes(b'\\x20\\x01'*16000)
if name=='pw-record':
    wav(args[-1])
    def stop_recording(*_):
        if (root/'recording-error').exists():
            print('Fixture recorder failure',file=sys.stderr)
        if (root/'recording-truncated').exists():
            path=Path(args[-1]);path.write_bytes(path.read_bytes()[:-4])
        status=root/'recording-exit'
        sys.exit(int(status.read_text()) if status.exists() else 1)
    signal.signal(signal.SIGINT,stop_recording)
    (root/'microphone-ready').touch()
    while True: time.sleep(.02)
elif name=='voxtype':
    (root/'setup-args').write_text(json.dumps(args))
    print(json.dumps(dict(event='progress',pct=50)),flush=True)
    time.sleep(.05)
    if (root/'download-failure').exists():
        print('Fixture download failed',file=sys.stderr);sys.exit(1)
    model=args[args.index('--model')+1]
    path=Path(os.environ['XDG_DATA_HOME'])/('voxtype/models/ggml-'+model+'.bin')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b'fake-model')
elif name=='ffmpeg':
    if (root/'decode-failure').exists():
        print('Cannot decode audio',file=sys.stderr);sys.exit(1)
    wav(args[-1])
elif name=='whisper-cli':
    (root/'whisper-args').write_text(json.dumps(args))
    if (root/'transcribe-failure').exists():
        print('PRIVATE_TRANSCRIPT');sys.exit(1)
    Path(args[args.index('-of')+1]+'.txt').write_text('' if (root/'empty-transcript').exists() else 'Hello · Xin chào · Здравей\\n')
elif name=='wl-copy':
    (root/'clipboard').write_bytes(sys.stdin.buffer.read())
    (root/'clipboard-pid').write_text(str(os.getpid()))
    while True: time.sleep(.02)
elif name=='notify-send':
    with (root/'notifications').open('a') as log:log.write(json.dumps(args)+'\\n')
    print('42',flush=True)
    if any(arg.startswith('--action=') for arg in args):
        def close_notice(*_):
            (root/'prompt-closed').touch();sys.exit(0)
        signal.signal(signal.SIGINT,close_notice)
        (root/'prompt-ready').touch()
        selected=root/'notification-action'
        while not selected.exists():time.sleep(.01)
        print(selected.read_text())
else: sys.exit(2)
"""
        )
        script.chmod(0o755)
        for name in (
            'pw-record',
            'voxtype',
            'ffmpeg',
            'whisper-cli',
            'wl-copy',
            'notify-send',
        ):
            (binary / name).symlink_to(script)
        env = patch.dict(
            os.environ,
            PATH=str(binary) + ':' + os.environ['PATH'],
            XDG_DATA_HOME=str(self.root / 'data'),
            XDG_CONFIG_HOME=str(self.root / 'config'),
            XDG_RUNTIME_DIR=str(self.root / 'runtime'),
            SPEECH_FIXTURE=str(self.root),
        )
        env.start()
        self.addCleanup(env.stop)
        self.default_microphone = 'test-microphone'
        self.sources = {
            'test-microphone': dict(
                name='test-microphone',
                index=12,
                mute=False,
                properties={'object.serial': '42'},
            )
        }

        def inspect_microphone(name=None):
            source = self.sources.get(name or self.default_microphone)
            if source is None:
                raise ValueError('No microphone is available.')
            return copy.deepcopy(source)

        def change_mute(source, muted):
            self.sources[source['name']]['mute'] = muted

        self.microphone = Mock(side_effect=inspect_microphone)
        self.mute_microphone = Mock(side_effect=change_mute)
        self.owner = speech.Speech(
            self.root / 'runtime',
            self.root / 'speech.json',
            self.root / 'Music/Recordings',
            lambda path, text: path.write_text(text),
            self.microphone,
            self.mute_microphone,
        )
        self.addCleanup(self.owner.close)
        target = patch.object(speech, 'active_window', return_value=('0x123', 'kitty'))
        target.start()
        self.addCleanup(target.stop)

    def ready_model(self):
        self.owner.model.parent.mkdir(parents=True, exist_ok=True)
        self.owner.model.write_bytes(b'fake model')

    def until(self, condition):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.owner.tick()
            if condition():
                return
            time.sleep(0.01)
        self.fail(f'Worker stalled: {self.owner.snapshot()}')

    def begin(self):
        self.owner.request({'op': 'speech-start'})
        self.until(lambda: (self.root / 'microphone-ready').exists())

    def approve_microphone(self):
        self.sources['test-microphone']['mute'] = True
        self.owner.request({'op': 'speech-start'})
        self.until(lambda: (self.root / 'prompt-ready').exists())
        self.assertEqual(self.owner.phase, 'microphone-muted')
        self.assertFalse((self.root / 'microphone-ready').exists())
        self.mute_microphone.assert_not_called()
        (self.root / 'notification-action').write_text('unmute')
        self.until(lambda: self.owner.phase == 'microphone-approved')
        (self.root / 'notification-action').unlink()
        self.assertTrue(self.sources['test-microphone']['mute'])

    def test_muted_microphone_waits_for_action_and_restores_before_transcription(self):
        self.ready_model()
        self.approve_microphone()
        self.owner.request({'op': 'speech-resume'})
        self.until(lambda: (self.root / 'microphone-ready').exists())
        self.assertFalse(self.sources['test-microphone']['mute'])
        self.owner.request({'op': 'speech-stop'})
        self.assertTrue(self.sources['test-microphone']['mute'])
        self.until(lambda: self.owner.phase == 'idle')
        self.assertEqual(self.owner.message, 'Transcript copied.')
        self.assertEqual(
            [call.args[1] for call in self.mute_microphone.call_args_list],
            [False, True],
        )

    def test_microphone_unavailable_offers_controls_without_recording(self):
        self.ready_model()
        self.sources.clear()
        self.owner.request({'op': 'speech-start'})
        self.until(lambda: (self.root / 'prompt-ready').exists())
        self.assertEqual(self.owner.phase, 'microphone-unavailable')
        self.assertFalse(self.owner.open_microphone_controls)
        (self.root / 'notification-action').write_text('controls')
        self.until(lambda: self.owner.open_microphone_controls)
        self.assertEqual(self.owner.phase, 'idle')
        self.assertFalse((self.root / 'microphone-ready').exists())
        self.mute_microphone.assert_not_called()
        self.owner.request({'op': 'speech-controls-opened'})
        self.assertFalse(self.owner.open_microphone_controls)

    def test_cancelled_or_expired_prompt_cannot_unmute(self):
        self.ready_model()
        for expire in (False, True):
            with self.subTest(expire=expire):
                self.sources['test-microphone']['mute'] = True
                self.owner.request({'op': 'speech-start'})
                self.until(lambda: (self.root / 'prompt-ready').exists())
                if expire:
                    self.owner.deadline = time.monotonic() - 1
                    self.owner.tick()
                else:
                    self.owner.cancel()
                self.until(lambda: not self.owner.notification.busy)
                self.assertEqual(self.owner.phase, 'idle')
                self.assertTrue(self.sources['test-microphone']['mute'])
                self.mute_microphone.assert_not_called()
                with self.assertRaisesRegex(ValueError, 'expired'):
                    self.owner.request({'op': 'speech-resume'})
                (self.root / 'prompt-ready').unlink()

    def test_default_microphone_change_invalidates_unmute_approval(self):
        self.ready_model()
        self.approve_microphone()
        self.sources['other'] = dict(
            name='other', index=13, mute=True, properties={'object.serial': '43'}
        )
        self.default_microphone = 'other'
        with self.assertRaisesRegex(ValueError, 'microphone changed'):
            self.owner.request({'op': 'speech-resume'})
        self.mute_microphone.assert_not_called()
        self.assertFalse((self.root / 'microphone-ready').exists())

    def test_temporary_unmute_restores_on_cancel_crash_and_start_failure(self):
        self.ready_model()
        for ending in ('cancel', 'crash', 'spawn-failure', 'close'):
            with self.subTest(ending=ending):
                self.mute_microphone.reset_mock()
                self.approve_microphone()
                if ending == 'spawn-failure':
                    with patch.object(
                        self.owner, 'spawn', side_effect=OSError('fixture start failed')
                    ):
                        with self.assertRaises(OSError):
                            self.owner.request({'op': 'speech-resume'})
                else:
                    self.owner.request({'op': 'speech-resume'})
                    self.until(lambda: (self.root / 'microphone-ready').exists())
                    if ending == 'cancel':
                        self.owner.cancel()
                    elif ending == 'close':
                        self.owner.close()
                    else:
                        self.owner.process.kill()
                        self.owner.process.wait()
                        self.owner.tick()
                self.assertTrue(self.sources['test-microphone']['mute'])
                self.assertEqual(self.owner.phase, 'idle')
                self.until(lambda: not self.owner.notification.busy)
                (self.root / 'microphone-ready').unlink(missing_ok=True)
                (self.root / 'prompt-ready').unlink(missing_ok=True)

    def test_restore_uses_original_device_and_skips_replacements(self):
        self.ready_model()
        for replace in (False, True):
            with self.subTest(replace=replace):
                self.mute_microphone.reset_mock()
                self.approve_microphone()
                self.owner.request({'op': 'speech-resume'})
                self.until(lambda: (self.root / 'microphone-ready').exists())
                if replace:
                    self.sources['test-microphone']['properties']['object.serial'] = (
                        '99'
                    )
                else:
                    self.sources['other'] = dict(
                        name='other',
                        index=13,
                        mute=False,
                        properties={'object.serial': '43'},
                    )
                    self.default_microphone = 'other'
                self.owner.cancel()
                self.assertEqual(
                    len(self.mute_microphone.call_args_list), 1 if replace else 2
                )
                if not replace:
                    self.assertFalse(self.sources['other']['mute'])
                self.default_microphone = 'test-microphone'
                (self.root / 'microphone-ready').unlink()
                (self.root / 'prompt-ready').unlink()

    def test_failed_mute_restore_keeps_actionable_warning_after_completion(self):
        self.ready_model()
        self.approve_microphone()
        self.owner.request({'op': 'speech-resume'})
        self.until(lambda: (self.root / 'microphone-ready').exists())
        self.mute_microphone.side_effect = OSError('fixture mute failed')
        self.owner.request({'op': 'speech-stop'})
        self.until(
            lambda: (
                self.owner.phase == 'idle'
                and self.owner.notification.action == 'controls'
                and not self.owner.notification.cancelling
                and not self.owner.notification.pending
                and 'Transcript copied.'
                in (self.root / 'notifications').read_text().splitlines()[-1]
            )
        )
        self.assertFalse(self.sources['test-microphone']['mute'])
        notices = [
            json.loads(line)
            for line in (self.root / 'notifications').read_text().splitlines()
        ]
        self.assertIn('Microphone could not be muted', notices[-1])
        self.assertIn('Transcript copied.', notices[-1][-1])
        (self.root / 'notification-action').write_text('controls')
        self.until(lambda: self.owner.open_microphone_controls)

    def test_input_that_stays_muted_offers_controls_without_recording(self):
        self.ready_model()
        self.approve_microphone()
        self.mute_microphone.side_effect = lambda source, muted: None
        self.owner.request({'op': 'speech-resume'})
        self.assertEqual(self.owner.phase, 'microphone-unavailable')
        self.assertTrue(self.sources['test-microphone']['mute'])
        self.assertFalse((self.root / 'microphone-ready').exists())
        self.until(lambda: self.owner.notification.action == 'controls')
        (self.root / 'notification-action').write_text('controls')
        self.until(lambda: self.owner.open_microphone_controls)

    def test_failed_mute_restore_warning_survives_recorder_failure(self):
        self.ready_model()
        self.approve_microphone()
        self.owner.request({'op': 'speech-resume'})
        self.until(lambda: (self.root / 'microphone-ready').exists())
        self.mute_microphone.side_effect = OSError('fixture mute failed')
        self.owner.process.kill()
        self.owner.process.wait()
        self.until(
            lambda: (
                self.owner.phase == 'idle'
                and self.owner.notification.action == 'controls'
            )
        )
        self.until(
            lambda: (
                (self.root / 'notifications').exists()
                and 'Microphone could not be muted'
                in (self.root / 'notifications').read_text().splitlines()[-1]
            )
        )
        self.assertFalse(self.sources['test-microphone']['mute'])
        (self.root / 'notification-action').write_text('controls')
        self.until(lambda: self.owner.open_microphone_controls)

    def test_setup_does_not_record_and_options_persist_with_validation(self):
        self.owner.request({'op': 'speech-setup'})
        self.until(lambda: self.owner.phase == 'idle')
        self.assertTrue(self.owner.snapshot()['modelReady'])
        self.microphone.assert_not_called()
        for key, value in (('language', 'bg'), ('mode', 'audio'), ('paste', True)):
            self.owner.request(dict(op='speech-option', key=key, value=value))
        self.assertEqual(
            json.loads(self.owner.preference.read_text()),
            dict(language='bg', mode='audio', paste=True, model='small'),
        )
        for key, value in (('language', 'shell'), ('paste', 'true'), ('mode', 'both')):
            with self.assertRaises(ValueError):
                self.owner.request(dict(op='speech-option', key=key, value=value))
        for output, mode, paste in (
            ('copy', 'transcribe', False),
            ('paste', 'transcribe', True),
            ('audio', 'audio', False),
        ):
            self.owner.request(dict(op='speech-output', value=output))
            saved = json.loads(self.owner.preference.read_text())
            self.assertEqual((saved['mode'], saved['paste']), (mode, paste))
        with self.assertRaisesRegex(ValueError, 'Unknown speech output'):
            self.owner.request(dict(op='speech-output', value='unknown'))

    def test_transcription_uses_selected_language_and_keeps_clipboard_owner(self):
        self.ready_model()
        self.owner.options.update(language='vi')
        self.begin()
        self.owner.request({'op': 'speech-stop'})
        self.until(lambda: self.owner.phase == 'idle')
        self.assertFalse(self.owner.error)
        self.assertEqual(
            (self.root / 'clipboard').read_text().strip(), 'Hello · Xin chào · Здравей'
        )
        args = json.loads((self.root / 'whisper-args').read_text())
        self.assertEqual(args[args.index('-l') + 1], 'vi')
        self.assertTrue(self.owner.keep_alive)
        self.assertIsNone(self.owner.clipboard.poll())
        self.assertEqual(list((self.root / 'runtime').iterdir()), [])

    def test_all_engine_languages_and_selected_models_are_exposed(self):
        catalog = speech.language_catalog()
        self.assertGreaterEqual(len(catalog), 100)
        available = self.owner.snapshot()['languages']
        self.assertEqual(len(available), 100)  # Auto + 99 languages in small.
        self.assertTrue(
            {'fr', 'ja', 'vi', 'bg'}.issubset({item['code'] for item in available})
        )
        self.assertNotIn('yue', {item['code'] for item in available})
        self.owner.request(dict(op='speech-option', key='model', value='large-v3'))
        self.assertIn('yue', {item['code'] for item in self.owner.languages()})
        self.owner.request(dict(op='speech-option', key='language', value='yue'))
        self.owner.request(dict(op='speech-option', key='model', value='small'))
        self.assertEqual(self.owner.options['language'], 'auto')
        with self.assertRaisesRegex(ValueError, 'different speech model'):
            self.owner.request(dict(op='speech-option', key='language', value='yue'))

    def test_failed_or_truncated_recording_preserves_clipboard_and_does_not_transcribe(
        self,
    ):
        self.ready_model()
        (self.root / 'clipboard').write_text('previous clipboard')
        for status, flag, expected in (
            (1, 'recording-error', 'Fixture recorder failure'),
            (2, None, 'Could not finish the microphone recording'),
            (1, 'recording-truncated', 'incomplete'),
            (0, 'recording-truncated', 'incomplete'),
        ):
            with self.subTest(status=status, flag=flag):
                (self.root / 'recording-exit').write_text(str(status))
                if flag:
                    (self.root / flag).touch()
                self.begin()
                self.owner.request({'op': 'speech-stop'})
                self.until(
                    lambda: (
                        self.owner.phase == 'idle' and not self.owner.notification.busy
                    )
                )
                self.assertIn(expected, self.owner.error)
                self.assertFalse((self.root / 'whisper-args').exists())
                self.assertEqual(
                    (self.root / 'clipboard').read_text(), 'previous clipboard'
                )
                self.assertEqual(list((self.root / 'runtime').iterdir()), [])
                if flag:
                    (self.root / flag).unlink()
                (self.root / 'microphone-ready').unlink()

    def test_model_selection_download_and_notification_replacement(self):
        self.ready_model()
        self.owner.request(dict(op='speech-option', key='model', value='tiny'))
        self.assertFalse(self.owner.snapshot()['modelReady'])
        self.owner.request(dict(op='speech-setup'))
        self.until(
            lambda: self.owner.phase == 'idle' and not self.owner.notification.busy
        )
        self.assertTrue(self.owner.snapshot()['modelReady'])
        self.assertTrue(self.owner.model_path('small').is_file())
        args = json.loads((self.root / 'setup-args').read_text())
        self.assertEqual(args[args.index('--model') + 1], 'tiny')
        notifications = [
            json.loads(line)
            for line in (self.root / 'notifications').read_text().splitlines()
        ]
        self.assertIn('--replace-id=0', notifications[0])
        self.assertIn('--replace-id=42', notifications[-1])
        self.assertIn('--hint=int:value:100', notifications[-1])
        self.assertIn('Whisper Tiny ready.', notifications[-1])
        self.owner.request(dict(op='speech-option', key='model', value='small'))
        self.assertTrue(self.owner.snapshot()['modelReady'])

    def test_failed_download_finishes_its_notification_and_preserves_installed_models(
        self,
    ):
        self.ready_model()
        self.owner.request(dict(op='speech-option', key='model', value='base'))
        (self.root / 'download-failure').touch()
        self.owner.request(dict(op='speech-setup'))
        self.until(
            lambda: self.owner.phase == 'idle' and not self.owner.notification.busy
        )
        self.assertIn('Fixture download failed', self.owner.error)
        self.assertTrue(self.owner.model_path('small').is_file())
        self.assertFalse(self.owner.model_ready('base'))
        notifications = [
            json.loads(line)
            for line in (self.root / 'notifications').read_text().splitlines()
        ]
        self.assertIn('Speech model download failed', notifications[-1])

    def test_audio_only_needs_no_model_and_does_not_transcribe(self):
        self.owner.options.update(mode='audio', paste=True)
        self.begin()
        with self.assertRaisesRegex(ValueError, 'Finish'):
            self.owner.request(dict(op='speech-option', key='language', value='en'))
        self.owner.request({'op': 'speech-stop'})
        self.until(lambda: self.owner.phase == 'idle')
        self.assertTrue(Path(self.owner.last_audio).is_file())
        with wave.open(self.owner.last_audio) as audio:
            self.assertGreater(audio.getnframes(), 0)
        self.assertFalse((self.root / 'whisper-args').exists())
        self.assertFalse((self.root / 'clipboard').exists())
        self.until(lambda: not self.owner.notification.busy)
        notice = json.loads((self.root / 'notifications').read_text().splitlines()[-1])
        self.assertIn('Audio saved.', notice)
        self.assertIn(self.owner.last_audio, notice)
        self.assertNotIn('--transient', notice)

    def test_empty_speech_and_failed_inference_notify_without_replacing_clipboard(self):
        self.ready_model()
        (self.root / 'clipboard').write_text('previous clipboard')
        for flag, title in (
            ('empty-transcript', 'No speech detected.'),
            ('transcribe-failure', 'Speech capture failed'),
        ):
            with self.subTest(flag=flag):
                (self.root / flag).touch()
                self.begin()
                self.owner.request({'op': 'speech-stop'})
                self.until(
                    lambda: (
                        self.owner.phase == 'idle' and not self.owner.notification.busy
                    )
                )
                notice = json.loads(
                    (self.root / 'notifications').read_text().splitlines()[-1]
                )
                self.assertIn(title, notice)
                self.assertNotIn('--transient', notice)
                self.assertNotIn('PRIVATE_TRANSCRIPT', json.dumps(notice))
                self.assertNotIn('PRIVATE_TRANSCRIPT', self.owner.error)
                self.assertEqual(
                    (self.root / 'clipboard').read_text(), 'previous clipboard'
                )
                self.assertEqual(list((self.root / 'runtime').iterdir()), [])
                (self.root / flag).unlink()
                (self.root / 'microphone-ready').unlink()

    def test_discard_removes_only_temporary_audio(self):
        self.owner.options['mode'] = 'audio'
        self.begin()
        process = self.owner.process
        self.owner.request({'op': 'speech-cancel'})
        self.assertIsNotNone(process.poll())
        self.assertEqual(self.owner.phase, 'idle')
        self.assertFalse(self.owner.folder.exists())
        self.assertEqual(list((self.root / 'runtime').iterdir()), [])

    def test_file_import_does_not_record_or_paste_and_preserves_input(self):
        self.ready_model()
        source = self.root / 'голос $(literal).mp3'
        source.write_bytes(b'input left alone')
        self.owner.options.update(language='bg', paste=True)
        with patch.object(speech, 'paste_into') as paste:
            self.owner.request(dict(op='speech-file', path=str(source)))
            self.until(lambda: self.owner.phase == 'idle')
            paste.assert_not_called()
        self.microphone.assert_not_called()
        self.assertEqual(source.read_bytes(), b'input left alone')
        self.assertFalse(self.owner.error)

    def test_decode_failure_preserves_clipboard_and_cleans_temporary_files(self):
        self.ready_model()
        (self.root / 'decode-failure').touch()
        (self.root / 'clipboard').write_text('previous clipboard')
        source = self.root / 'broken.wav'
        source.write_bytes(b'bad audio')
        self.owner.request(dict(op='speech-file', path=str(source)))
        self.until(lambda: self.owner.phase == 'idle')
        self.assertIn('Cannot decode', self.owner.error)
        self.assertEqual((self.root / 'clipboard').read_text(), 'previous clipboard')
        self.assertEqual(list((self.root / 'runtime').iterdir()), [])

    def test_auto_paste_requires_original_app_and_no_shell_surface(self):
        self.ready_model()
        self.owner.options['paste'] = True
        self.owner.request(dict(op='speech-context', blocked=False))
        with patch.object(speech, 'paste_into', return_value=True) as paste:
            self.begin()
            self.owner.request({'op': 'speech-stop'})
            self.until(lambda: self.owner.phase == 'idle')
            paste.assert_called_once_with(('0x123', 'kitty'))
            self.assertEqual(self.owner.message, 'Transcript pasted.')
        (self.root / 'microphone-ready').unlink()
        self.owner.request(dict(op='speech-context', blocked=True))
        with patch.object(speech, 'paste_into') as paste:
            self.begin()
            self.owner.request({'op': 'speech-stop'})
            self.until(lambda: self.owner.phase == 'idle')
            paste.assert_not_called()
            self.assertEqual(self.owner.message, 'Transcript copied.')
            self.until(lambda: not self.owner.notification.busy)
            notice = json.loads(
                (self.root / 'notifications').read_text().splitlines()[-1]
            )
            self.assertIn(
                'Automatic paste skipped. Paste from the clipboard when ready.', notice
            )

    def test_recording_limit_finishes_and_saves_audio(self):
        self.owner.options['mode'] = 'audio'
        self.begin()
        self.owner.since = time.monotonic() - speech.FILE_LIMIT - 1
        self.owner.tick()
        self.assertEqual(self.owner.phase, 'stopping')
        self.until(lambda: self.owner.phase == 'idle')
        self.assertTrue(Path(self.owner.last_audio).is_file())

    def test_native_paste_checks_target_and_uses_terminal_shortcut(self):
        with patch.object(speech.subprocess, 'run') as run:
            self.assertFalse(speech.paste_into(('0x456', 'kitty')))
            run.assert_not_called()
            self.assertTrue(speech.paste_into(('0x123', 'kitty')))
            command = run.call_args.args[0]
            self.assertIn('"CTRL SHIFT"', command[-1])
            self.assertIn('address:0x123', command[-1])
            self.assertNotIn('Return', command[-1])

    def test_control_reconnect_recovers_speech_and_preserves_clipboard_until_replaced(
        self,
    ):
        self.ready_model()
        runtime = self.root / 'runtime'
        runtime.mkdir()
        endpoint = runtime / 'desktop-capture/control.sock'
        endpoint.parent.mkdir()
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(endpoint))
        listener.listen()
        self.addCleanup(listener.close)
        backend = support.DESKTOP / 'drawers/capture/recorder.py'
        script = (
            'import importlib.util,os,pathlib,sys;os.dup2(int(sys.argv[2]),3);os.environ["LISTEN_PID"]=str(os.getpid());os.environ["LISTEN_FDS"]="1";sys.path.insert(0,str(pathlib.Path(sys.argv[1]).parent));'
            's=importlib.util.spec_from_file_location("r",sys.argv[1]);r=importlib.util.module_from_spec(s);s.loader.exec_module(r);'
            'r.location=lambda kind:pathlib.Path(os.environ["XDG_RUNTIME_DIR"])/kind;'
            'r.check_microphone=lambda:dict(name="test-microphone",index=12,mute=False,properties={});r.IDLE_EXIT=.2;r.serve()'
        )
        process = subprocess.Popen(
            [sys.executable, '-B', '-c', script, str(backend), str(listener.fileno())],
            pass_fds=(listener.fileno(),),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        def stop():
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)

        self.addCleanup(stop)
        deadline = time.monotonic() + 4
        while not endpoint.exists() and time.monotonic() < deadline:
            time.sleep(0.02)

        def request(operation):
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(2)
                client.connect(str(endpoint))
                client.sendall((json.dumps({'op': operation}) + '\n').encode())
                with client.makefile('r') as replies:
                    return json.loads(replies.readline())['speech']

        self.assertEqual(request('speech-start')['phase'], 'recording')
        deadline = time.monotonic() + 3
        while (
            not (self.root / 'microphone-ready').exists()
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        self.assertEqual(request('status')['phase'], 'recording')
        request('speech-stop')
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if request('status')['phase'] == 'idle':
                break
            time.sleep(0.03)
        else:
            self.fail('Transcription did not finish after reconnect')
        time.sleep(0.35)
        self.assertIsNone(process.poll(), 'Clipboard provider lost with idle service')
        os.kill(int((self.root / 'clipboard-pid').read_text()), signal.SIGTERM)
        self.assertEqual(process.wait(timeout=3), 0)


class FakeControl:
    def __init__(self, root, *, ready=False, recording=False, microphone_issue=None):
        self.microphone_issue = microphone_issue
        self.approved_at = 0
        self.resumed_after = 0
        self.speech = dict(
            phase='recording' if recording else 'idle',
            modelReady=ready,
            options=dict(speech.DEFAULTS),
            elapsed=0,
            error='',
            message='',
            progress=-1,
            folder='/tmp/voice',
            lastAudio='',
            openMicrophoneControls=False,
            languages=[dict(code='auto', name='Auto-detect')]
            + [
                dict(code=item['code'], name=item['name'])
                for item in speech.language_catalog()
                if item['id'] < 99
            ],
            models=[
                dict(
                    id=name,
                    name=meta['name'],
                    size=meta['size'],
                    installed=ready and name == 'small',
                )
                for name, meta in speech.MODELS.items()
            ],
        )
        self.requests = []
        self.deadline = 0
        directory = root / 'runtime/desktop-capture'
        directory.mkdir()
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(directory / 'control.sock'))
        self.server.listen()
        self.server.settimeout(0.05)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=2)
        self.server.close()

    def state(self, reply=False):
        return (
            json.dumps(
                dict(
                    available=True,
                    phase='idle',
                    options={},
                    pictures='',
                    videos='',
                    speech=self.speech,
                    reply=reply,
                )
            )
            + '\n'
        ).encode()

    def serve(self):
        while not self.stopped.is_set():
            try:
                connection, _ = self.server.accept()
            except TimeoutError:
                continue
            with connection:
                connection.settimeout(0.03)
                buffer = b''
                while not self.stopped.is_set():
                    try:
                        data = connection.recv(8192)
                        if not data:
                            break
                        buffer += data
                    except TimeoutError:
                        pass
                    try:
                        while b'\n' in buffer:
                            line, _, buffer = buffer.partition(b'\n')
                            request = json.loads(line)
                            self.requests.append(request)
                            op = request['op']
                            if op == 'speech-setup':
                                self.speech['phase'] = 'preparing'
                                self.deadline = time.monotonic() + 0.12
                            elif op == 'speech-option':
                                self.speech['options'][request['key']] = request[
                                    'value'
                                ]
                                if request['key'] == 'model':
                                    self.speech['modelReady'] = next(
                                        model['installed']
                                        for model in self.speech['models']
                                        if model['id'] == request['value']
                                    )
                            elif op == 'speech-output':
                                self.speech['options'].update(
                                    mode='audio'
                                    if request['value'] == 'audio'
                                    else 'transcribe',
                                    paste=request['value'] == 'paste',
                                )
                            elif op == 'speech-start':
                                self.speech['phase'] = (
                                    'microphone-' + self.microphone_issue
                                    if self.microphone_issue
                                    else 'recording'
                                )
                            elif op == 'fixture-microphone-action':
                                if request['value'] == 'unmute':
                                    self.speech['phase'] = 'microphone-approved'
                                    self.approved_at = time.monotonic()
                                else:
                                    self.speech.update(
                                        phase='idle', openMicrophoneControls=True
                                    )
                            elif op == 'speech-resume':
                                self.resumed_after = time.monotonic() - self.approved_at
                                self.speech['phase'] = 'recording'
                            elif op == 'speech-controls-opened':
                                self.speech['openMicrophoneControls'] = False
                            elif op in ('speech-stop', 'speech-file'):
                                self.speech['phase'] = 'transcribing'
                                self.deadline = time.monotonic() + 0.15
                            elif op == 'speech-cancel':
                                self.speech['phase'] = 'idle'
                            connection.sendall(self.state(True))
                        if (
                            self.speech['phase'] in ('preparing', 'transcribing')
                            and time.monotonic() > self.deadline
                        ):
                            self.speech.update(phase='idle', modelReady=True)
                            for model in self.speech['models']:
                                if model['id'] == self.speech['options']['model']:
                                    model['installed'] = True
                            connection.sendall(self.state())
                    except (BrokenPipeError, ConnectionResetError):
                        break


PREAMBLE = """import QtQuick
import QtTest
import Quickshell
import "ui"
import "drawers"
import "drawers/capture"
ShellRoot {
 id:test
 property int step:0
 property int ticks:0
 property int hides:0
 function check(ok,message){if(!ok){console.log("DISPLAY_FAIL",message);Qt.quit();}}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children||[]){const found=find(child,name);if(found)return found;}return null;}
 TestCase{id:input;when:false;parent:window.contentItem}
 FloatingWindow{id:window;implicitWidth:460;implicitHeight:650;visible:true
  CaptureDrawer{id:drawer;anchors.fill:parent;active:true;webcams:[]}
 }
 Connections{target:DictationService
  function onHideRequested(){test.hides++;drawer.active=false;}
 }
 Component.onCompleted:CaptureService.start()
 Timer{interval:40;running:true;repeat:true;onTriggered:{
  test.ticks++;
  if(test.ticks>200){console.log("DISPLAY_FAIL","speech timed out",test.step,DictationService.phase,DictationService.error);Qt.quit();}
"""
END = ' } }\n}\n'


@unittest.skipUnless(support.QS, 'Quickshell is required')
class SpeechDrawerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('notify-send'), 'libnotify is required')
    def test_native_notification_action_and_cancellation(self):
        def setup(root):
            (root / 'notification-probe.py').write_text("""import sys,time
from pathlib import Path
root=Path(__file__).parent
sys.path.insert(0,str(root/'drawers/capture'))
from speech import SpeechNotification
notice=SpeechNotification()
notice.update('Microphone is muted','It will be muted again when recording stops.',finished=True,action=('unmute','Unmute and transcribe'))
mode=sys.argv[1]
cancelled=False
deadline=time.monotonic()+6
try:
    while time.monotonic()<deadline:
        action=notice.tick()
        if action:
            print(action,flush=True);break
        request=root/'config/cancel-prompt'
        if request.exists() and request.read_text()==mode and not cancelled:
            cancelled=True
            if mode=='expire':notice.deadline=time.monotonic()-1
            else:notice.cancel_prompt()
        if cancelled and not notice.busy:
            print(mode,flush=True);break
        time.sleep(.02)
    else:raise RuntimeError('notification did not complete')
finally:notice.close()
""")

        support.run_qml(
            self,
            """import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/notifications"
ShellRoot {
 id:root
 property int stage:0
 property int ticks:0
 property int firstId:0
 property string mode:"action"
 property string result:""
 Component.onCompleted:NotificationCenter.start()
 FileView{id:cancel;path:Quickshell.env("XDG_CONFIG_HOME")+"/cancel-prompt"}
 Process{id:worker;command:["python3",Quickshell.shellPath("notification-probe.py"),root.mode]
  stdout:SplitParser{onRead:line=>root.result=line.trim()}
  onExited:code=>{if(code!==0){console.log("DISPLAY_FAIL notification helper",code);Qt.quit();}}
 }
 Timer{interval:40;running:true;repeat:true;onTriggered:{try{
  root.ticks++;
  const row=NotificationCenter.state.items.find(item=>item.summary==="Microphone is muted");
  if(stage===0&&NotificationCenter.initialized){worker.running=true;stage++;
  }else if(stage===1&&row){
   if(row.actions.length!==1||row.actions[0].text!=="Unmute and transcribe")throw Error("notification action missing");
   firstId=row.liveId;NotificationCenter.invoke(row.id,"unmute");stage++;
  }else if(stage===2&&!worker.running&&result==="unmute"){
   mode="cancel";result="";worker.running=true;stage++;
  }else if(stage===3&&row&&row.liveId!==firstId){cancel.setText("cancel");stage++;
  }else if(stage===4&&!worker.running&&result==="cancel"&&(!row||row.liveId===firstId)){
   mode="expire";result="";worker.running=true;stage++;
  }else if(stage===5&&row&&row.liveId!==firstId){cancel.setText("expire");stage++;
  }else if(stage===6&&!worker.running&&result==="expire"&&(!row||row.liveId===firstId)){console.log("DISPLAY_PASS");Qt.quit();}
  if(ticks>230)throw Error("notification timed out at "+stage+" result="+result+" running="+worker.running+" row="+JSON.stringify(row));
 }catch(e){console.log("DISPLAY_FAIL",e);Qt.quit();}}}
}
""",
            setup,
            isolate_bus=True,
        )

    def control(self, *, picker=None, cancel=False, **kwargs):
        def setup(root):
            self.fake = FakeControl(root, **kwargs)
            self.addCleanup(self.fake.close)
            if picker is not None:
                command = root / 'picker'
                command.write_text(
                    f'#!{sys.executable}\n'
                    + f"""import sys,time
from pathlib import Path
root=Path({str(root)!r})
closed=root/'config/picker-closed'
assert closed.exists(), 'drawer retained input'
assert time.time()*1000-float(closed.read_text())>=300, 'picker started before drawer exit'
time.sleep(.1)
if {cancel!r}: sys.exit(1)
print({picker!r})
"""
                )
                command.chmod(0o755)
                source = root / 'drawers/capture/DictationService.qml'
                source.write_text(
                    source.read_text().replace('"zenity"', json.dumps(str(command)))
                )

        return setup

    def test_unmute_action_dismisses_surfaces_before_resuming_recording(self):
        support.run_qml(
            self,
            PREAMBLE
            + """
  if(test.step===0&&DictationService.ready&&!DictationService.pending){
   DictationService.toggle();test.step++;
  }else if(test.step===1&&DictationService.phase==="microphone-muted"&&!DictationService.pending){
   check(DictationService.waitingForMicrophone&&DictationService.canCancel,"muted request cannot cancel");
   check(test.hides===1&&!drawer.active,"muted request retained the drawer");
   check(find(drawer,"captureSpeech").text==="Cancel","waiting action has no cancel label");
   CaptureService.send({op:"fixture-microphone-action",value:"unmute"});test.step++;
  }else if(test.step===2&&DictationService.starting){
   check(test.hides===2&&!drawer.active,"approval did not dismiss surfaces");
   drawer.active=true;DictationService.guardDismissal();
   check(test.hides===3&&!drawer.active,"reopened surface was not dismissed before resume");test.step++;
  }else if(test.step===3&&DictationService.recording&&!DictationService.pending){console.log("DISPLAY_PASS");Qt.quit();}
"""
            + END,
            self.control(ready=True, microphone_issue='muted'),
        )
        self.assertGreaterEqual(self.fake.resumed_after, 0.35)
        self.assertEqual(
            sum(item['op'] == 'speech-resume' for item in self.fake.requests), 1
        )

    def test_microphone_controls_open_only_after_notification_action(self):
        body = PREAMBLE.replace(
            ' property int hides:0',
            ' property int hides:0\n property int controls:0\n Connections{target:DictationService;function onMicrophoneSettingsRequested(){test.controls++;}}',
        )
        support.run_qml(
            self,
            body
            + """
  if(test.step===0&&DictationService.ready&&!DictationService.pending){
   DictationService.toggle();test.step++;
  }else if(test.step===1&&DictationService.phase==="microphone-unavailable"&&!DictationService.pending){
   check(!test.controls&&!drawer.active,"unavailable microphone opened controls automatically");
   CaptureService.send({op:"fixture-microphone-action",value:"controls"});test.step++;
  }else if(test.step===2&&test.controls&&!DictationService.pending){
   check(test.controls===1&&!DictationService.openMicrophoneControls,"controls request repeated or was not acknowledged");
   console.log("DISPLAY_PASS");Qt.quit();
  }
"""
            + END,
            self.control(ready=True, microphone_issue='unavailable'),
        )
        self.assertFalse(
            any(item['op'] == 'speech-resume' for item in self.fake.requests)
        )

    def test_three_buttons_language_output_options_and_file_selection(self):
        support.run_qml(
            self,
            PREAMBLE
            + """
  if(test.step===0&&DictationService.ready&&!DictationService.pending){
   const shot=find(drawer,"captureScreenshot"),video=find(drawer,"captureRecording"),speak=find(drawer,"captureSpeech");
   check(Math.abs(shot.y-speak.y)<1&&Math.abs(video.y-speak.y)<1,"speech is not in capture row");
   check(Math.abs(shot.width-speak.width)<2,"third button width differs");
   find(drawer,"captureSpeechOptions").clicked();test.step++;
  }else if(test.step===1&&drawer.speechMenu.visible){
   check(drawer.escapeHandler,"speech popup does not own Escape");
   find(drawer.speechMenu.contentItem,"speechLanguage").activated(DictationService.languages.findIndex(item=>item.code==="bg"));test.step++;
  }else if(test.step===2&&DictationService.options.language==="bg"&&!DictationService.pending){
   find(drawer.speechMenu.contentItem,"speechOutput").activated(1);test.step++;
  }else if(test.step===3&&DictationService.options.paste&&!DictationService.pending){
   find(drawer.speechMenu.contentItem,"speechOutput").activated(2);test.step++;
  }else if(test.step===4&&DictationService.options.mode==="audio"&&!DictationService.pending){
   check(!find(drawer.speechMenu.contentItem,"speechLanguage").visible,"language visible in audio mode");
   check(!find(drawer.speechMenu.contentItem,"speechModel").visible,"model visible in audio mode");
   check(find(drawer,"captureSpeech").text==="Record audio","audio action not labelled");
   drawer.width=268;check(drawer.escapeHandler()&&!drawer.speechMenu.visible,"Escape failed");
   check(DictationService.transcribeFile("file:///tmp/voice%20%D0%B1%D0%B3.mp3"),"file rejected");test.step++;
  }else if(test.step===5&&DictationService.processing){
   check(!DictationService.transcribeFile("file:///tmp/other.wav"),"concurrent file accepted");test.step++;
  }else if(test.step===6&&!DictationService.active&&!DictationService.pending){console.log("DISPLAY_PASS");Qt.quit();}
"""
            + END,
            self.control(ready=True),
        )
        imported = next(
            item for item in self.fake.requests if item['op'] == 'speech-file'
        )
        self.assertEqual(imported['path'], '/tmp/voice бг.mp3')

    def test_language_search_selects_matching_language_and_resets_on_reopen(self):
        support.run_qml(
            self,
            PREAMBLE
            + """
  const language=find(drawer.speechMenu.contentItem,"speechLanguage");
  if(test.step===0&&DictationService.ready&&!DictationService.pending){
   find(drawer,"captureSpeechOptions").clicked();test.step++;
  }else if(test.step===1&&drawer.speechMenu.visible){
   language.popup.open();test.step++;
  }else if(test.step===2&&language.popup.visible){
   const search=find(language.popup.contentItem,"speechLanguageSearch");
   check(search.activeFocus,"language search did not gain focus");
   search.text="no-such-language";
   check(!language.matchingIndices.length&&find(language.popup.contentItem,"speechLanguageNoMatches").visible,"no-match state missing");
   search.text="  BULG  ";
   check(language.matchingIndices.length===1,"language-name search failed");
   search.text="bg";
   check(language.matchingIndices.length===1,"language-code search failed");
   input.keyClick(Qt.Key_Return);test.step++;
  }else if(test.step===3&&DictationService.options.language==="bg"&&!DictationService.pending){
   check(!language.popup.visible,"language selection kept dropdown open");
   check(language.currentIndex===DictationService.languages.findIndex(item=>item.code==="bg"),"filtered index replaced source index");
   language.popup.open();test.step++;
  }else if(test.step===4&&language.popup.visible){
   const search=find(language.popup.contentItem,"speechLanguageSearch");
   check(!search.text&&language.matchingIndices.length===DictationService.languages.length,"reopening retained search");
   search.text="japan";test.step++;
  }else if(test.step===5){
   const index=language.matchingIndices[0];
   const option=find(language.popup.contentItem,"speechLanguageOption:"+index);
   check(option&&option.text==="Japanese","matching language was not rendered");
   input.mouseClick(option,option.width/2,option.height/2);test.step++;
  }else if(test.step===6&&DictationService.options.language==="ja"&&!DictationService.pending){
   drawer.active=false;
   CaptureService.recorder=Object.assign({},CaptureService.recorder,{speech:Object.assign({},DictationService.state,{error:"Fixture failure",message:"Audio saved."})});
   check(!drawer.active&&!drawer.speechMenu.visible,"speech result reopened drawer");
   check(!find(drawer,"dictationError")&&!find(drawer,"dictationStatus").visible,"speech outcome appeared inline");
   console.log("DISPLAY_PASS");Qt.quit();
  }
"""
            + END,
            self.control(ready=True),
        )

    def test_setup_then_start_and_stop_with_drawer_closed(self):
        support.run_qml(
            self,
            PREAMBLE
            + """
  if(test.step===0&&DictationService.ready&&!DictationService.pending){
   check(!DictationService.modelReady,"fake model present");find(drawer,"captureSpeechAction").clicked();test.step++;
  }else if(test.step===1&&DictationService.modelReady&&!DictationService.pending){
   check(test.hides===1&&!DictationService.recording,"setup did not hand off to background download");drawer.active=true;find(drawer,"captureSpeechAction").clicked();
   check(!DictationService.toggle(),"duplicate start accepted");test.step++;
  }else if(test.step===2&&DictationService.recording&&!DictationService.pending){
   check(test.hides===2&&!drawer.active,"capture did not dismiss");check(DictationService.toggle(),"closed drawer could not stop");test.step++;
  }else if(test.step===3&&DictationService.processing){
   check(!DictationService.toggle(),"transcription started another job");test.step++;
  }else if(test.step===4&&!DictationService.active&&!DictationService.pending){console.log("DISPLAY_PASS");Qt.quit();}
"""
            + END,
            self.control(),
        )
        self.assertEqual(
            [
                r['op']
                for r in self.fake.requests
                if r['op'] in ('speech-start', 'speech-stop')
            ],
            ['speech-start', 'speech-stop'],
        )

    def test_reload_recovers_session_and_discard_does_not_start_another(self):
        support.run_qml(
            self,
            PREAMBLE
            + """
  if(test.step===0&&DictationService.recording&&!DictationService.pending){
   check(test.hides===0,"reload started another capture");find(drawer,"dictationCancel").clicked();test.step++;
  }else if(test.step===1&&!DictationService.active&&!DictationService.pending){console.log("DISPLAY_PASS");Qt.quit();}
"""
            + END,
            self.control(ready=True, recording=True),
        )
        self.assertFalse(any(r['op'] == 'speech-start' for r in self.fake.requests))

    def test_model_dropdown_selects_size_without_automatically_downloading(self):
        support.run_qml(
            self,
            PREAMBLE
            + """
  if(test.step===0&&DictationService.ready&&!DictationService.pending){
   find(drawer,"captureSpeechOptions").clicked();test.step++;
  }else if(test.step===1&&drawer.speechMenu.visible){
   const choice=find(drawer.speechMenu.contentItem,"speechModel");
   check(choice.count===6,"model sizes are missing");
   choice.activated(0);test.step++;
  }else if(test.step===2&&DictationService.options.model==="tiny"&&!DictationService.pending){
   check(!DictationService.modelReady&&!DictationService.preparing,"model selection started download");
   check(find(drawer.speechMenu.contentItem,"speechSetup").text.includes("75 MB"),"wrong selected download size");
   check(DictationService.languages.some(item=>item.code==="ja"),"language catalogue is still restricted");
   console.log("DISPLAY_PASS");Qt.quit();
  }
"""
            + END,
            self.control(ready=True),
        )
        self.assertFalse(any(r['op'] == 'speech-setup' for r in self.fake.requests))

    def test_file_chooser_survives_drawer_destruction_and_cancel_releases_it(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                body = """import QtQuick
import Quickshell
import Quickshell.Io
import "drawers"
import "drawers/capture"
ShellRoot {
 id:test
 property int step:0
 property int ticks:0
 FileView{id:closed;path:Quickshell.env("XDG_CONFIG_HOME")+"/picker-closed"}
 FloatingWindow{implicitWidth:460;implicitHeight:650;visible:true
  Loader{id:page;anchors.fill:parent;sourceComponent:Component{CaptureDrawer{active:true;webcams:[]}}}
 }
 Connections{target:DictationService
  function onHideRequested(){closed.setText(String(Date.now()));page.active=false;}
 }
 function check(ok,message){if(!ok){console.log("DISPLAY_FAIL",message);Qt.quit();}}
 Component.onCompleted:CaptureService.start()
 Timer{interval:40;running:true;repeat:true;onTriggered:{
  test.ticks++;if(test.ticks>150){console.log("DISPLAY_FAIL","picker timed out",DictationService.error);Qt.quit();}
  if(test.step===0&&DictationService.ready&&!DictationService.pending){
   check(DictationService.chooseFile(),"picker rejected");
   check(!DictationService.chooseFile(),"duplicate picker accepted");test.step++;
  }else if(test.step===1&&test.ticks>5&&!DictationService.pending&&!DictationService.active){
   check(!page.item,"drawer survived chooser handoff");check(!DictationService.error,"picker failed: "+DictationService.error);
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }}
}
"""
                support.run_qml(
                    self,
                    body,
                    self.control(
                        ready=True, picker='/tmp/voice бг #.mp3', cancel=cancel
                    ),
                )
                files = [r for r in self.fake.requests if r['op'] == 'speech-file']
                self.assertEqual(
                    files,
                    []
                    if cancel
                    else [dict(op='speech-file', path='/tmp/voice бг #.mp3')],
                )


if __name__ == '__main__':
    unittest.main()
