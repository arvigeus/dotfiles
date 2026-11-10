"""File clients share the speech owner without using real audio or the clipboard."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import support
from test_dictation import FakeControl

SHARED = (
    support.REPO
    / 'modules/media/tools/transcription/files/usr/local/lib/desktop-speech'
)


class TranscriptionDialogTests(unittest.TestCase):
    def run_panel(self, script, *, legacy=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'runtime').mkdir()
            fake = FakeControl(root, ready=True)
            if legacy:
                fake.speech.pop('fileOutputs')
            try:
                env = dict(
                    os.environ,
                    QT_QPA_PLATFORM='offscreen',
                    XDG_RUNTIME_DIR=str(root / 'runtime'),
                    PYTHONPATH=str(SHARED),
                    TRANSCRIPTION_TEST_ROOT=str(root),
                )
                setup = """
import os, time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from speech_gui import TranscriptionPanel
root = Path(os.environ['TRANSCRIPTION_TEST_ROOT'])
source = root / 'Movie · бг.mkv'
source.write_bytes(b'original')
app = QApplication([])
w = TranscriptionPanel(lambda: source, video=True)
w.resize(760, 500)
w.show()
def wait_for(condition):
    deadline = time.monotonic() + 4
    while not condition():
        app.processEvents()
        assert time.monotonic() < deadline, w.message.text()
        time.sleep(.005)
wait_for(lambda: w.start.isEnabled() or 'updated transcription service' in w.message.text())
"""
                result = subprocess.run(
                    [sys.executable, '-c', setup + script],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                return fake.requests
            finally:
                fake.close()

    def test_video_subtitles_options_completion_and_background_ownership(self):
        requests = self.run_panel("""
assert w.models.count() == 6
assert w.languages.count() > 90
w.output.setCurrentIndex(w.output.findData('srt'))
w.start.click()
wait_for(lambda: w.state.get('phase') == 'transcribing')
assert w.busy and not w.models.isEnabled() and w.cancel.isEnabled()
wait_for(lambda: not w.busy)
assert w.message.text() == str(source.with_suffix('.srt'))
assert w.start.isEnabled()
w.start.click()
wait_for(lambda: w.state.get('phase') == 'transcribing')
w.close()
app.processEvents()
""")
        files = [item for item in requests if item['op'] == 'speech-file']
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]['output'], 'srt')
        self.assertEqual(files[0]['language'], 'auto')
        self.assertEqual(files[0]['model'], 'small')
        self.assertNotEqual(files[0]['jobId'], files[1]['jobId'])
        self.assertFalse(any(item['op'] == 'speech-cancel' for item in requests))

    def test_audio_clipboard_and_cancel_only_the_current_job(self):
        requests = self.run_panel("""
w.close()
w.socket.abort()
audio = TranscriptionPanel(lambda: source)
audio.show()
wait_for(lambda: audio.start.isEnabled())
assert not audio.output.isVisible()
audio.start.click()
wait_for(lambda: audio.state.get('phase') == 'transcribing')
audio.cancel.click()
wait_for(lambda: not audio.busy)
assert audio.message.text() == 'Cancelled.'
audio.close()
""")
        job = next(item for item in requests if item['op'] == 'speech-file')
        cancel = next(item for item in requests if item['op'] == 'speech-cancel')
        self.assertEqual(job['output'], 'clipboard')
        self.assertEqual(cancel['jobId'], job['jobId'])

    def test_older_running_service_cannot_silently_copy_subtitle_requests(self):
        requests = self.run_panel(
            """
assert not w.start.isEnabled()
assert 'Reboot' in w.message.text()
w.output.setCurrentIndex(1)
w.start.click()
app.processEvents()
w.close()
""",
            legacy=True,
        )
        self.assertFalse(any(item['op'] == 'speech-file' for item in requests))

    def test_busy_service_refuses_start_and_reopened_panel_recovers_job(self):
        self.run_panel("""
w.start.click()
wait_for(lambda: w.state.get('phase') == 'transcribing')
identifier = w.job_id
w.close()
w.socket.abort()
other = TranscriptionPanel(lambda: source, video=True)
other.show()
wait_for(lambda: other.busy)
assert other.job_id == identifier
assert not other.start.isEnabled()
other.cancel.click()
wait_for(lambda: not other.busy)
other.close()
""")


@unittest.skipUnless(support.QS, 'Quickshell is required')
class LibraryTranscriptionTests(unittest.TestCase):
    def test_movie_and_episode_subtitle_button_navigates_recovers_and_refreshes(self):
        for space in ('movies', 'series'):
            with self.subTest(space=space):

                def setup(root):
                    self.fake = FakeControl(root, ready=True)
                    self.addCleanup(self.fake.close)
                    # Inventory remains local and deterministic; no catalogue/account access.
                    backend = root / 'spaces/movies/subtitle_backend.py'
                    backend.write_text(
                        'import json,sys\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps(dict(id=r["id"],result=dict(files=[],embedded=[],release={},fps=24,languages=["en"]))))\n sys.stdout.flush()\n'
                    )

                body = """import QtQuick
import Quickshell
import "spaces/movies"
import "drawers/capture"
ShellRoot {
 id:test
 property int step:0
 property int ticks:0
 function check(ok,message){if(!ok){console.log("DISPLAY_FAIL",message);Qt.quit();}}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children||[]){const result=find(child,name);if(result)return result;}return null;}
 FloatingWindow { implicitWidth:900;implicitHeight:600;visible:true
  Subtitles {id:panel;anchors.fill:parent;spaceId:SPACE;files:[{path:"/tmp/Movie · бг.mkv"},{path:"/tmp/Series S01E02.mkv",season:1,episode:2}]}
 }
 Timer {interval:15;running:true;repeat:true;onTriggered:{
  test.ticks++;if(test.ticks>400){console.log("DISPLAY_FAIL","timed out",test.step,panel.error);Qt.quit();}
  const action=find(panel,"generateSubtitles");
  if(test.step===0&&action.enabled&&!panel.loading){
   check(action.text==="Generate subtitles","missing accessible action");
   action.clicked();test.step++;
  }else if(test.step===1&&panel.generating){
   check(action.text==="Cancel subtitle generation","no cancel action");
   panel.path="/tmp/Series S01E02.mkv";
   check(!panel.generating&&!action.enabled,"other episode can interfere with active job");
   panel.path="/tmp/Movie · бг.mkv";
   check(panel.generating&&action.enabled,"returning did not recover active job");test.step++;
  }else if(test.step===2&&!panel.generating&&!panel.loading){
   check(panel.info.includes("Movie · бг.srt"),"completion did not refresh/report sidecar");
   panel.path="/tmp/Series S01E02.mkv";action.clicked();test.step++;
  }else if(test.step===3&&panel.generating){action.clicked();test.step++;
  }else if(test.step===4&&!panel.generating){
   check(panel.info==="Cancelled.","cancel result missing");console.log("DISPLAY_PASS");Qt.quit();
  }
 }}
}
""".replace('SPACE', '"' + space + '"')
                support.run_qml(self, body, setup)
                jobs = [
                    item for item in self.fake.requests if item['op'] == 'speech-file'
                ]
                self.assertEqual(len(jobs), 2)
                self.assertTrue(all(item['output'] == 'srt' for item in jobs))
                cancel = next(
                    item for item in self.fake.requests if item['op'] == 'speech-cancel'
                )
                self.assertEqual(cancel['jobId'], jobs[-1]['jobId'])


if __name__ == '__main__':
    unittest.main()
