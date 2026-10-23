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
    def run_dialog(self, script):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', AUDIO_TEST_DIR=folder,
                       AUDIO_TEST_CONFIG=str(CONFIG), PYTHONPATH=str(LIB))
            setup = '''
import os, subprocess, time
from pathlib import Path
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QApplication
import gui
import core
root = Path(os.environ['AUDIO_TEST_DIR'])
source = root / 'song.flac'
subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=0.2', '-metadata', 'title=Original', str(source)], check=True)
original = source.read_bytes()
app = QApplication([])
w = gui.AudioTools([source], Path(os.environ['AUDIO_TEST_CONFIG']))
w.show()
def wait_for(condition):
 deadline = time.monotonic() + 15
 while not condition():
  app.processEvents()
  if time.monotonic() > deadline: raise AssertionError('Dialog timed out: ' + w.status.text())
  time.sleep(0.005)
wait_for(lambda: source in w.info)
'''
            result = subprocess.run([sys.executable, '-c', setup + script], env=env,
                                    capture_output=True, text=True, timeout=45, check=False)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_tag_save_conversion_and_error_keep_the_dialog_responsive(self):
        self.run_dialog('''
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
''')

    def test_cancel_removes_partial_output_and_keeps_source(self):
        self.run_dialog('''
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
''')

    def test_batch_save_changes_only_edited_fields(self):
        self.run_dialog('''
second = root / 'second.flac'
subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-c', 'copy', '-metadata', 'title=Second title', str(second)], check=True)
w.append_files([second])
field = w.fields['album']
field.setText('Shared album'); field.textEdited.emit('Shared album')
w.batch.setChecked(True)
gui.QMessageBox.question = lambda *args: gui.QMessageBox.StandardButton.Yes
w.save_tags()
wait_for(lambda: not w.active)
for path, title in [(source, 'Original'), (second, 'Second title')]:
 info = core.audio_info(subprocess.check_output(core.probe_command(path)))
 assert info['tags']['album'] == 'Shared album'
 assert info['tags']['title'] == title
assert w.failures == 0, w.log.toPlainText()
w.stop_probe(); w.close()
''')


if __name__ == '__main__':
    unittest.main()
