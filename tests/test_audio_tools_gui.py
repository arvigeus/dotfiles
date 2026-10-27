"""The real Qt dialog saves, converts, reports failures and cancels safely."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / 'modules/media/tools/audio/files/usr/local/lib/audio-tools'
CONFIG = REPO / 'modules/media/tools/audio/files/home/.config/audio-tools/presets.json'


class AudioDialogTests(unittest.TestCase):
    def run_dialog(self, script, source_suffix='.flac'):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(
                os.environ,
                QT_QPA_PLATFORM='offscreen',
                AUDIO_TEST_DIR=folder,
                AUDIO_TEST_CONFIG=str(CONFIG),
                AUDIO_TEST_SUFFIX=source_suffix,
                PYTHONPATH=str(LIB),
                XDG_CONFIG_HOME=str(Path(folder) / 'config'),
            )
            setup = """
import os, subprocess, time
from pathlib import Path
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QApplication
import gui
import core
root = Path(os.environ['AUDIO_TEST_DIR'])
source = root / ('song' + os.environ['AUDIO_TEST_SUFFIX'])
subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=0.2', '-metadata', 'title=Original', str(source)], check=True)
original = source.read_bytes()
app = QApplication([])
w = gui.AudioTools(source, Path(os.environ['AUDIO_TEST_CONFIG']))
w.show()
def wait_for(condition):
 deadline = time.monotonic() + 15
 while not condition():
  app.processEvents()
  if time.monotonic() > deadline: raise AssertionError('Dialog timed out: ' + w.status.text())
  time.sleep(0.005)
wait_for(lambda: source in w.info)
"""
            result = subprocess.run(
                [sys.executable, '-c', setup + script],
                env=env,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_tag_save_conversion_and_error_keep_the_dialog_responsive(self):
        self.run_dialog("""
# Artwork is a clickable preview next to the heading, with a separate delete icon.
from unittest.mock import patch
from PySide6.QtWidgets import QPushButton
assert w.cover.isEnabled() and not w.cover_remove.isEnabled()
with patch.object(gui.QFileDialog, 'getOpenFileName', return_value=('', '')) as picker:
 w.cover.click(); assert picker.called
assert w.cover.geometry().top()<w.fields['title'].parentWidget().mapTo(w,w.fields['title'].geometry().topLeft()).y()
assert not any('presets' in b.text().lower() for b in w.findChildren(QPushButton))
field = w.fields['title']
field.setText('New title'); field.textEdited.emit('New title')
w.backup.setChecked(True)
w.save_tags()
wait_for(lambda: not w.active and source in w.info)
assert w.info[source]['tags']['title'] == 'New title'
assert Path(str(source) + '.tags-backup').read_bytes() == original
w.start_conversion()
wait_for(lambda: not w.active)
assert (root / 'song [aac-320].m4a').exists()
assert w.failures == 0, w.log.toPlainText()
# An output collision is reported without replacing the completed output.
output = (root / 'song [aac-320].m4a').read_bytes()
w.start_conversion()
wait_for(lambda: not w.active)
assert w.failures == 1 and 'already exists' in w.log.toPlainText()
assert (root / 'song [aac-320].m4a').read_bytes() == output
# Failed remuxes retain unsaved edits and remove temporary files.
field.setText('Retain this draft'); field.textEdited.emit('Retain this draft')
real = gui.tag_edit
def failed(*args):
 operation = real(*args)
 operation.command = ['ffmpeg', '-invalid-audio-tools-test-option']
 return operation
gui.tag_edit = failed
w.save_tags()
wait_for(lambda: not w.active and source in w.info)
assert w.failures == 1
assert w.drafts[source]['title'] == 'Retain this draft'
assert w.info[source]['tags']['title'] == 'New title'
assert not list(root.glob('.audio-tools-*'))
w.drafts.clear(); w.stop_probe(); w.close()
""")

    def test_cancel_removes_partial_output_and_keeps_source(self):
        self.run_dialog("""
import sys
real = gui.conversion
def delayed(*args):
 operation = real(*args)
 operation.temporary.write_text('partial output')
 operation.command = [sys.executable, '-c', 'import time; time.sleep(30)']
 return operation
gui.conversion = delayed
w.start_conversion()
wait_for(lambda: w.process.state() == QProcess.ProcessState.Running)
# Escape follows the same cancellation path and cannot close an active job.
w.reject()
assert w.isVisible()
wait_for(lambda: not w.active)
assert w.cancelled
assert source.read_bytes() == original
assert not (root / 'song [aac-320].m4a').exists()
assert not list(root.glob('.audio-tools-*'))
w.stop_probe(); w.close()
""")

    def test_opus_tags_with_existing_cover_save_in_the_real_dialog(self):
        self.run_dialog(
            """
import base64
from mutagen.flac import Picture
from mutagen.oggopus import OggOpus
w.stop_probe()
cover = root / 'cover.png'
subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=80x80','-frames:v','1',str(cover)],check=True)
picture = Picture(); picture.type = 3; picture.mime = 'image/png'; picture.data = cover.read_bytes()
audio = OggOpus(source)
audio['metadata_block_picture'] = [base64.b64encode(picture.write()).decode('ascii')]
audio.save()
original_cover = audio['metadata_block_picture']
w.info.clear(); w.inspect_file()
wait_for(lambda: source in w.info)
assert w.info[source]['artwork'] == 1
for key,value in {'title':'Smile (Pearl Jam cover)','artist':'Glen Hansard'}.items():
 w.fields[key].setText(value); w.fields[key].textEdited.emit(value)
w.save_tags()
wait_for(lambda: not w.active and source in w.info)
assert w.failures == 0, w.log.toPlainText()
assert w.info[source]['tags']['title'] == 'Smile (Pearl Jam cover)'
assert w.info[source]['tags']['artist'] == 'Glen Hansard'
assert w.info[source]['artwork'] == 1
assert OggOpus(source)['metadata_block_picture'] == original_cover
assert not list(root.glob('.audio-tools-*'))
w.stop_probe(); w.close()
""",
            source_suffix='.opus',
        )

    def test_single_file_save_changes_only_edited_fields(self):
        self.run_dialog("""
from PySide6.QtWidgets import QListWidget, QPushButton, QSplitter
assert not w.findChildren(QListWidget) and not w.findChildren(QSplitter)
assert not any('Add file' in b.text() for b in w.findChildren(QPushButton))
assert not hasattr(w, 'batch')
assert source.name in w.windowTitle()
field = w.fields['album']
field.setText('New album'); field.textEdited.emit('New album')
w.save_tags()
wait_for(lambda: not w.active and source in w.info)
assert w.info[source]['tags']['album'] == 'New album'
assert w.info[source]['tags']['title'] == 'Original'
assert not list(root.glob('*.tags-backup*'))
assert w.failures == 0, w.log.toPlainText()
w.stop_probe(); w.close()
""")

    def test_fetch_lyrics_uses_shared_config_keeps_drafts_and_saves_without_changing_audio(
        self,
    ):
        self.run_dialog("""
import json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import audio_lyrics
requests = []
class Handler(BaseHTTPRequestHandler):
 def log_message(self, *_): pass
 def do_GET(self):
  requests.append((self.path, self.headers.get('Authorization')))
  body = json.dumps(dict(plainLyrics='Fetched line one\\nFetched line two')).encode()
  self.send_response(200); self.end_headers(); self.wfile.write(body)
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
settings = audio_lyrics.config_path(); settings.parent.mkdir(parents=True)
settings.write_text(json.dumps(dict(version=1, providers=[dict(name='Fixture',base_url=f'http://127.0.0.1:{server.server_port}/api',api_key='private-fixture-token')])))
artist = w.fields['artist']; artist.setText('Fixture artist'); artist.textEdited.emit(artist.text())
assert w.lyrics_fetch.isEnabled()
before = subprocess.check_output(['ffmpeg','-v','error','-i',str(source),'-f','md5','-'])
w.lyrics_fetch.click()
assert w.lyrics_request and w.lyrics_fetch.text() == 'Cancel fetch'
# Qt stays responsive during the lookup, and fetched text remains a draft.
wait_for(lambda: w.lyrics_request is None)
assert w.fields['lyrics'].toPlainText() == 'Fetched line one\\nFetched line two', w.status.text()
assert requests[0][1] == 'Bearer private-fixture-token'
assert 'track_name=Original' in requests[0][0] and 'artist_name=Fixture+artist' in requests[0][0]
assert source.read_bytes() == original
assert w.drafts[source]['lyrics'] == w.fields['lyrics'].toPlainText()
w.save_tags(); wait_for(lambda: not w.active and source in w.info)
assert w.failures == 0, w.log.toPlainText()
assert w.info[source]['tags']['lyrics'] == 'Fetched line one\\nFetched line two'
assert subprocess.check_output(['ffmpeg','-v','error','-i',str(source),'-f','md5','-']) == before
# Refusing to replace existing lyrics leaves the draft untouched.
with patch.object(gui.QMessageBox, 'question', return_value=gui.QMessageBox.StandardButton.No):
 w.lyrics_fetch.click()
assert not w.lyrics_request and len(requests) == 1
server.shutdown(); server.server_close(); w.stop_probe(); w.close()
""")

    def test_lyrics_errors_cancellation_and_edits_do_not_replace_the_draft(self):
        self.run_dialog("""
import json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import audio_lyrics
mode = {'status': 503, 'delay': 0}
class Handler(BaseHTTPRequestHandler):
 def log_message(self, *_): pass
 def do_GET(self):
  time.sleep(mode['delay'])
  self.send_response(mode['status']); self.end_headers()
  try: self.wfile.write(json.dumps(dict(plainLyrics='Late lyrics')).encode())
  except BrokenPipeError: pass
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
settings = audio_lyrics.config_path(); settings.parent.mkdir(parents=True)
settings.write_text(json.dumps(dict(version=1,providers=[dict(base_url=f'http://127.0.0.1:{server.server_port}')])))
artist = w.fields['artist']; artist.setText('Artist'); artist.textEdited.emit(artist.text())
w.lyrics_fetch.click(); wait_for(lambda: not w.lyrics_request)
assert 'unavailable' in w.status.text() and not w.fields['lyrics'].toPlainText()
mode.update(status=200, delay=1)
w.lyrics_fetch.click(); wait_for(lambda: w.lyrics_process.state() == QProcess.ProcessState.Running)
w.lyrics_fetch.click()
assert not w.lyrics_request and w.lyrics_fetch.text() == 'Fetch lyrics'
w.lyrics_fetch.click(); wait_for(lambda: w.lyrics_process.state() == QProcess.ProcessState.Running)
w.fields['lyrics'].setPlainText('User edited lyrics')
assert not w.lyrics_request and w.fields['lyrics'].toPlainText() == 'User edited lyrics'
# Discard cancels the request before reloading tags; a closed window owns no helper.
w.discard_edits(); wait_for(lambda: source in w.info)
artist.setText('Artist'); artist.textEdited.emit('Artist')
w.lyrics_fetch.click(); wait_for(lambda: w.lyrics_process.state() == QProcess.ProcessState.Running)
w.discard_edits(); wait_for(lambda: source in w.info)
assert not w.lyrics_request and not w.fields['lyrics'].toPlainText()
artist.setText('Artist'); artist.textEdited.emit('Artist')
w.lyrics_fetch.click(); wait_for(lambda: w.lyrics_process.state() == QProcess.ProcessState.Running)
with patch.object(gui.QMessageBox, 'question', return_value=gui.QMessageBox.StandardButton.Yes): w.close()
assert w.lyrics_process.state() == QProcess.ProcessState.NotRunning
assert source.read_bytes() == original
server.shutdown(); server.server_close()
""")


if __name__ == '__main__':
    unittest.main()
