"""Video tools operate on generated media, never the user's video library."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / 'modules/media/tools/video'
LIB = MODULE / 'files/usr/local/lib/video-tools'
CONFIG = MODULE / 'files/home/.config/video-tools/presets.json'
sys.path.insert(0, str(LIB))
import video_core as core


class VideoToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "User's $(touch UNEXPECTED) video.mkv"
        subtitle = self.root / 'captions.srt'
        subtitle.write_text('1\n00:00:00,000 --> 00:00:00,900\nTest subtitle\n')
        metadata = self.root / 'metadata.txt'
        metadata.write_text(
            ';FFMETADATA1\ntitle=Video test\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=900\ntitle=Test chapter\n'
        )
        self.run_command(
            [
                'ffmpeg',
                '-v',
                'error',
                '-f',
                'lavfi',
                '-i',
                'testsrc2=size=128x72:rate=5:duration=1',
                '-f',
                'lavfi',
                '-i',
                'sine=duration=1',
                '-i',
                str(subtitle),
                '-i',
                str(metadata),
                '-map',
                '0:v',
                '-map',
                '1:a',
                '-map',
                '2:s',
                '-map_metadata',
                '3',
                '-map_chapters',
                '3',
                '-c:v',
                'libx264',
                '-preset',
                'ultrafast',
                '-c:a',
                'aac',
                '-c:s',
                'srt',
                str(self.source),
            ]
        )
        self.original = self.source.read_bytes()

    def run_command(self, command):
        return subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=30
        )

    def complete(self, operation):
        try:
            self.run_command(operation.command)
            operation.finish()
        finally:
            operation.abort()

    def test_every_preset_preserves_source_and_expected_tracks(self):
        for preset in core.read_presets(CONFIG):
            with self.subTest(preset=preset['id']):
                operation = core.conversion(self.source, preset)
                self.complete(operation)
                report = json.loads(
                    self.run_command(core.probe_command(operation.target)).stdout
                )
                kinds = [s['codec_type'] for s in report['streams']]
                self.assertEqual(
                    report['format']['tags'].get(
                        'title', report['format']['tags'].get('TITLE')
                    ),
                    'Video test',
                )
                if preset['mode'] == 'audio':
                    self.assertNotIn('video', kinds)
                    self.assertIn('audio', kinds)
                else:
                    self.assertIn('video', kinds)
                    self.assertIn('audio', kinds)
                    video = next(
                        s for s in report['streams'] if s['codec_type'] == 'video'
                    )
                    self.assertEqual(
                        video['codec_name'],
                        {'libvpx-vp9': 'vp9', 'libsvtav1': 'av1'}.get(
                            preset.get('codec'), 'h264'
                        ),
                    )
                    if preset.get('codec') == 'libsvtav1':
                        self.assertEqual(video['pix_fmt'], 'yuv420p10le')
                        self.run_command(
                            [
                                'ffmpeg',
                                '-v',
                                'error',
                                '-i',
                                str(operation.target),
                                '-map',
                                '0:v:0',
                                '-f',
                                'null',
                                '-',
                            ]
                        )
                    self.assertEqual((video['width'], video['height']), (128, 72))
                if preset['mode'] == 'copy':
                    self.assertIn('subtitle', kinds)
                    self.assertEqual(len(report['chapters']), 1)
                else:
                    self.assertNotIn('subtitle', kinds)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse((self.root / 'UNEXPECTED').exists())
        self.assertFalse(list(self.root.glob('.video-tools-*')))

    def test_av1_preset_settings_validate_encoder_specific_ranges(self):
        data = json.loads(CONFIG.read_text())
        preset = next(p for p in data['presets'] if p.get('codec') == 'libsvtav1')
        path = self.root / 'presets.json'
        for key, value in [
            ('quality', 64),
            ('speed', 'medium'),
            ('speed', 14),
            ('pixel_format', 'invalid'),
        ]:
            with self.subTest(key=key, value=value):
                invalid = dict(preset, **{key: value})
                path.write_text(json.dumps({'version': 1, 'presets': [invalid]}))
                with self.assertRaises(ValueError):
                    core.read_presets(path)
        path.write_text(
            json.dumps({'version': 1, 'presets': [dict(preset, quality=60, speed=10)]})
        )
        self.assertEqual(core.read_presets(path)[0]['quality'], 60)

    def test_output_race_and_abort_never_replace_existing_files(self):
        operation = core.conversion(self.source, core.read_presets(CONFIG)[0])
        self.run_command(operation.command)
        operation.target.write_text('keep me')
        with self.assertRaises(FileExistsError):
            operation.finish()
        self.assertEqual(operation.target.read_text(), 'keep me')
        with self.assertRaises(FileExistsError):
            core.conversion(self.source, core.read_presets(CONFIG)[0])
        operation = core.conversion(self.source, core.read_presets(CONFIG)[1])
        operation.abort()
        self.assertFalse(operation.target.exists())
        self.assertFalse(operation.temporary.exists())

    def test_real_dialog_info_conversion_and_cancellation(self):
        env = dict(
            os.environ,
            QT_QPA_PLATFORM='offscreen',
            PYTHONPATH=str(LIB),
            VIDEO_TEST_SOURCE=str(self.source),
            VIDEO_TEST_CONFIG=str(CONFIG),
        )
        script = """
import os, sys, time
from pathlib import Path
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication
import video_gui as gui
source=Path(os.environ['VIDEO_TEST_SOURCE']); original=source.read_bytes()
app=QApplication([]); w=gui.VideoTools(source,Path(os.environ['VIDEO_TEST_CONFIG']));w.show()
def wait_for(condition):
 deadline=time.monotonic()+15
 while not condition():
  app.processEvents()
  if time.monotonic()>deadline: raise AssertionError('Dialog timed out: '+w.status.text())
  time.sleep(0.005)
wait_for(lambda:source in w.info)
assert w.tree.topLevelItemCount()>=5
assert '128 × 72' in w.summary.text()
assert '1 sec' in w.summary.text()
for value, expected in [(0,'0 sec'), (9.5,'9.5 sec'), (59.96,'1 min 0 sec'), (596.5,'9 min 56.5 sec'), (3661,'1 hr 1 min 1 sec'), ('N/A','Unknown')]:
 assert gui.human_duration(value)==expected,(value,gui.human_duration(value))
from PySide6.QtWidgets import QListWidget, QPushButton, QSplitter
assert not w.findChildren(QListWidget) and not w.findChildren(QSplitter)
assert not any('Add file' in b.text() for b in w.findChildren(QPushButton))
assert source.name in w.windowTitle()
assert not any('VLC' in b.text() or 'presets' in b.text().lower() for b in w.findChildren(QPushButton))

w.start_conversion(); wait_for(lambda:not w.active)
assert w.failures==0,w.log.toPlainText()
assert next(source.parent.glob('*[[]mp4-h264[]].mp4')).exists()
w.presets.setCurrentIndex(1)
real=gui.conversion
def delayed(*args):
 op=real(*args);op.temporary.write_text('partial');op.command=[sys.executable,'-c','import time;time.sleep(30)'];return op
gui.conversion=delayed
w.start_conversion();wait_for(lambda:w.process.state()==QProcess.ProcessState.Running)
w.reject();assert w.isVisible()
wait_for(lambda:not w.active)
assert w.cancelled and not list(source.parent.glob('.video-tools-*'))
assert source.read_bytes()==original
w.close()
"""
        result = subprocess.run(
            [sys.executable, '-c', script],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
