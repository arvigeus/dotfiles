"""Exercise real test workers with fake audio clients; never access host audio."""

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

import test_audio_drawer as drawer_tests

DESKTOP, SINK, STREAM, backend = (
    drawer_tests.DESKTOP,
    drawer_tests.SINK,
    drawer_tests.STREAM,
    drawer_tests.backend,
)


WORKER = DESKTOP / 'drawers/audio/probe.py'
spec = importlib.util.spec_from_file_location('audio_probe', WORKER)
probe = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, backend=backend):
    spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_speakers_visit_all_unmuted_outputs_and_native_channels(self):
        first = dict(SINK, channel_map='front-left,front-right')
        second = dict(SINK, name='display', channel_map='front-center,lfe')
        muted = dict(SINK, name='muted', mute=True)
        unplugged = dict(SINK, name='gone', active_port='jack')
        runner = probe.Probe()
        with (
            patch.object(backend, 'load_config', return_value=({}, '')),
            patch.object(
                backend, 'read', return_value=[first, second, muted, unplugged]
            ),
            patch.object(probe, 'channel_audio', return_value=b'wav'),
            patch.object(probe, 'report'),
            patch.object(runner, 'play') as play,
        ):
            runner.speakers()
        self.assertEqual(
            [(call.args[0], call.kwargs['channel']) for call in play.call_args_list],
            [
                ('laptop', 'front-left'),
                ('laptop', 'front-right'),
                ('display', 'front-center'),
                ('display', 'lfe'),
            ],
        )

    def test_tone_fallback_is_a_bounded_mono_wave(self):
        for channel in ('lfe', 'top-front-left', 'aux0'):
            with wave.open(io.BytesIO(probe.channel_audio(channel))) as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getframerate(), probe.RATE)
                self.assertLess(wav.getnframes(), probe.RATE)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(probe, 'SAMPLES', Path(directory)),
        ):
            with self.assertRaisesRegex(ValueError, 'alsa-utils'):
                probe.channel_audio('front-left')
            sample = Path(directory) / 'Front_Left.wav'
            sample.write_bytes(b'voice')
            self.assertEqual(probe.channel_audio('front-left'), b'voice')

    def test_monitors_and_muted_inputs_cannot_start_recording(self):
        for source in (dict(SINK, name='speaker.monitor'), dict(SINK, mute=True)):
            with (
                patch.object(backend, 'read', return_value=[source]),
                patch.object(probe.subprocess, 'Popen') as spawn,
            ):
                with self.assertRaises(ValueError):
                    probe.Probe().record(source['name'])
                spawn.assert_not_called()


FAKE_CLIENT = r"""#!/usr/bin/env python3
import json,os,signal,sys,time
from pathlib import Path
name=Path(sys.argv[0]).name
root=Path(os.environ['FAKE_AUDIO'])
def log(event, **values):
 with (root/'events').open('a') as output: output.write(json.dumps(dict(event=event,pid=os.getpid(),**values))+'\n')
if name=='pactl':
 state=json.loads((root/'state').read_text())
 if sys.argv[-1]=='info': print(json.dumps(dict(default_source_name='mic',default_sink_name='laptop')))
 elif sys.argv[-2]=='list': print(json.dumps(state.get(sys.argv[-1],[])))
 else: raise SystemExit('Unexpected mutation: '+str(sys.argv))
elif name=='parec':
 signal.signal(signal.SIGTERM,lambda *_: sys.exit(0))
 log('record-start',args=sys.argv[1:])
 try:
  while True:
   sys.stdout.buffer.write(b'\x01\x00'*240);sys.stdout.buffer.flush();time.sleep(0.01)
 finally: log('record-stop')
elif name=='paplay':
 signal.signal(signal.SIGTERM,lambda *_: sys.exit(0))
 log('play-start',args=sys.argv[1:])
 try:
  data=sys.stdin.buffer.read()
  log('play-data',size=len(data))
  time.sleep(float(os.environ.get('FAKE_PLAY_DELAY','0.05')))
 finally: log('play-stop')
"""


class ProbeProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        client = self.root / 'client'
        client.write_text(FAKE_CLIENT)
        client.chmod(0o755)
        for name in ('pactl', 'parec', 'paplay'):
            (self.root / name).symlink_to(client)
        self.state = dict(
            sinks=[dict(SINK, channel_map='aux0,aux1')],
            sources=[dict(SINK, name='mic')],
        )
        self.save_state()
        self.env = {
            **os.environ,
            'PATH': str(self.root) + os.pathsep + os.environ['PATH'],
            'FAKE_AUDIO': str(self.root),
            'XDG_CONFIG_HOME': str(self.root / 'config'),
        }

    def save_state(self):
        temporary = self.root / 'state.tmp'
        temporary.write_text(json.dumps(self.state))
        temporary.replace(self.root / 'state')

    def events(self):
        path = self.root / 'events'
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def wait_event(self, name):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if any(event['event'] == name for event in self.events()):
                return
            time.sleep(0.02)
        self.fail('No ' + name + ' event')

    def start(self, op, record_seconds=None):
        command = [sys.executable, '-B', str(WORKER)]
        if record_seconds is not None:
            command = [
                sys.executable,
                '-B',
                '-c',
                f'import sys;sys.path.insert(0,{str(WORKER.parent)!r});import probe;probe.RECORD_SECONDS={record_seconds};probe.main()',
            ]
        process = subprocess.Popen(
            command,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def cleanup():
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()

        self.addCleanup(cleanup)
        process.stdin.write(json.dumps(dict(op=op)) + '\n')
        process.stdin.flush()
        return process

    def test_release_stops_capture_before_playback_and_preserves_pcm(self):
        process = self.start('microphone')
        self.wait_event('record-start')
        time.sleep(0.12)
        output, error = process.communicate('release\n', timeout=5)
        self.assertEqual(process.returncode, 0, error)
        self.assertNotIn('"phase": "error"', output)
        events = self.events()
        names = [event['event'] for event in events]
        self.assertLess(names.index('record-stop'), names.index('play-start'))
        played = next(event for event in events if event['event'] == 'play-data')
        self.assertGreater(played['size'], 0)
        self.assertLessEqual(played['size'], probe.RATE * 2 * probe.RECORD_SECONDS)
        play = next(event for event in events if event['event'] == 'play-start')
        self.assertIn('--device=laptop', play['args'])
        self.assertIn('--raw', play['args'])
        with self.assertRaises(ProcessLookupError):
            os.kill(
                next(
                    event['pid'] for event in events if event['event'] == 'record-start'
                ),
                0,
            )

    def test_cancel_and_stdin_closure_discard_recording(self):
        for cancel in (True, False):
            with self.subTest(cancel=cancel):
                (self.root / 'events').unlink(missing_ok=True)
                process = self.start('microphone')
                self.wait_event('record-start')
                if cancel:
                    process.terminate()
                process.communicate(timeout=5)
                self.assertIn('record-stop', [e['event'] for e in self.events()])
                self.assertNotIn('play-start', [e['event'] for e in self.events()])

    def test_release_sent_with_request_is_not_lost(self):
        result = subprocess.run(
            [sys.executable, '-B', str(WORKER)],
            env=self.env,
            input='{"op":"microphone"}\nrelease\n',
            text=True,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"phase": "done"', result.stdout)

    def test_recording_limit_stops_capture_but_waits_for_release(self):
        process = self.start('microphone', record_seconds=1)
        self.wait_event('record-stop')
        self.assertIsNone(process.poll())
        self.assertNotIn('play-start', [event['event'] for event in self.events()])
        output, _ = process.communicate('release\n', timeout=5)
        self.assertIn('"phase": "ready"', output)
        self.assertNotIn('"phase": "error"', output)
        played = next(event for event in self.events() if event['event'] == 'play-data')
        self.assertLessEqual(played['size'], probe.RATE * 2)

    def test_channel_clients_target_each_channel_without_remixing(self):
        result = subprocess.run(
            [sys.executable, '-B', str(WORKER)],
            env=self.env,
            input='{"op":"speakers"}\n',
            text=True,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"phase": "done"', result.stdout)
        plays = [e for e in self.events() if e['event'] == 'play-start']
        self.assertEqual(len(plays), 2)
        for event, channel in zip(plays, ('aux0', 'aux1')):
            self.assertIn('--device=laptop', event['args'])
            self.assertIn('--channel-map=' + channel, event['args'])
            self.assertIn('--no-remix', event['args'])

    def test_disconnect_aborts_playback_and_stops_the_client(self):
        self.env['FAKE_PLAY_DELAY'] = '5'
        process = self.start('speakers')
        self.wait_event('play-start')
        self.state['sinks'] = []
        self.save_state()
        output, _ = process.communicate(timeout=5)
        self.assertIn('no longer available', output)
        self.assertIn('play-stop', [e['event'] for e in self.events()])


@unittest.skipUnless(drawer_tests.QS, 'Quickshell is required')
class ProbeUiTests(unittest.TestCase):
    run_qml = drawer_tests.AudioDrawerTests.run_qml

    def test_worker_early_release_cancel_failure_and_restart(self):
        def setup(root):
            (root / 'fake-probe.py').write_text("""import json,sys,time
request=json.loads(sys.stdin.readline())
if request['op']=='microphone':
 print(json.dumps({'phase':'recording'}),flush=True)
 if sys.stdin.readline() != 'release\\n': raise SystemExit(2)
 print(json.dumps({'phase':'playback'}),flush=True)
 time.sleep(0.1)
 print(json.dumps({'phase':'done'}),flush=True)
elif request['op']=='speakers':
 print(json.dumps({'phase':'speakers','detail':'Left'}),flush=True)
 time.sleep(10)
elif request['op']=='error': print(json.dumps({'phase':'error','error':'Test device disconnected'}),flush=True)
""")

        self.run_qml(
            r"""import QtQuick
import Quickshell
import "drawers/audio"
ShellRoot {
 AudioTestService { id:tester; command:["python3","-u",Qt.resolvedUrl("fake-probe.py").toString().replace("file://","")] }
 function check(value,message) {if(!value) throw new Error(message);}
 property int stage:0
 Timer { interval:60;running:true;repeat:true;onTriggered: {
  try {
   if(stage===0) {tester.start("microphone");tester.release();stage++;}
   else if(stage===1 && !tester.running) {
    check(!tester.error && tester.completed,"early release was lost or preceded request");
    tester.start("speakers");stage++;
   } else if(stage===2 && tester.detail==="Left") {tester.cancel();stage++;}
   else if(stage===3 && !tester.running) {
    check(!tester.error,"cancel became an error");tester.start("error");stage++;
   } else if(stage===4 && !tester.running) {
    check(tester.error==="Test device disconnected","worker error missing");tester.start("incomplete");stage++;
   } else if(stage===5 && !tester.running) {
    check(tester.error!=="","unexpected helper exit accepted as success");
    tester.start("microphone");tester.release();stage++;
   } else if(stage===6 && !tester.running) {
    check(!tester.error && tester.completed,"worker did not recover after failure");console.log("AUDIO_PASS");Qt.quit();
   }
  } catch(error) {console.error("AUDIO_FAIL",error.message);Qt.quit();}
 } }
}
""",
            setup,
        )

    def test_footer_mouse_keyboard_release_and_drawer_cancellation(self):
        outputs, devices = backend.output_inventory([SINK], [], {})
        source = dict(outputs[0], key='mic', name='mic', label='Built-in microphone')
        state = dict(
            available=True,
            outputs=outputs,
            outputDevices=devices,
            inputs=[source],
            inputDevices=[],
            warning='',
        )
        self.run_qml(
            r"""import QtQuick
import QtTest
import Quickshell
import "drawers"
import "ui" as UI
FloatingWindow {
 id: window; implicitWidth:480; implicitHeight:720
 property int pageWidth:448
FAKE_SERVICE component Tester: QtObject {
  property bool running:false
  property string phase:"idle"
  property string error:""
  property string detail:""
  property int starts:0
  property int releases:0
  property int cancels:0
  function start(kind) { starts++; running=true; phase=kind === "microphone" ? "recording" : "speakers"; }
  function release() { releases++; phase="playback"; }
  function cancel() { if(running) { cancels++;running=false;phase="idle"; } }
 }
 Tester { id:speakers }
 Tester { id:microphone }
 SoundDrawer {
  id:sound; width:window.pageWidth; height:688; service:fake; audioTest:speakers; active:true
  Rectangle {anchors.fill:parent;z:-1;color:UI.Theme.background}
 }
 MicrophoneDrawer {
  id:mic; width:window.pageWidth; height:688; service:fake; audioTest:microphone; active:false; visible:false
  Rectangle {anchors.fill:parent;z:-1;color:UI.Theme.background}
 }
 TestCase { id:input; when:false; parent:window.contentItem }
 function find(item,name) {
  if(item.objectName === name) return item;
  for(const child of item.children || []) { const value=find(child,name);if(value) return value; }
  return null;
 }
 function check(value,message) { if(!value) throw new Error(message); }
 function capture(name) {
  const directory=PREVIEW_DIR;
  if(directory) (mic.visible ? mic : sound).grabToImage(result => result.saveToFile(directory+"/"+name));
 }
 property int stage:0
 Timer { interval:120; running:true; repeat:true; onTriggered: {
  try {
   const speakerButton=find(sound,"speakerTestButton"), micButton=find(mic,"microphoneTestButton");
   if(stage === 0) {
    fake.node("laptop"); fake.node("mic", {isSink:false}); fake.defaultSink="laptop"; fake.defaultSource="mic";
    check(speakerButton.enabled,"speaker test unavailable");
    input.mouseClick(speakerButton,speakerButton.width/2,speakerButton.height/2);
    check(speakers.starts === 1 && speakers.running,"speaker test did not start");
    capture("speakers.png");
    input.mouseClick(speakerButton,speakerButton.width/2,speakerButton.height/2);
    check(speakers.cancels === 1,"speaker test did not stop");
    speakers.start("speakers");sound.active=false;sound.visible=false;mic.visible=true;mic.active=true;
   } else if(stage === 1) {
    check(!speakers.running,"speaker test survived drawer dismissal");
    check(micButton.enabled,"default microphone test unavailable");
    input.mousePress(micButton,micButton.width/2,micButton.height/2);
    check(microphone.starts === 1 && microphone.releases === 0,"press did not start capture");
    capture("microphone-recording.png");
   } else if(stage === 2) {
    input.mouseRelease(micButton,micButton.width/2,micButton.height/2);
    check(microphone.releases === 1 && microphone.cancels === 0 && microphone.running,"release cancelled playback");
    capture("microphone-playback.png");
    input.mouseClick(micButton,micButton.width/2,micButton.height/2);
    check(!microphone.running && microphone.cancels === 1,"playback click did not cancel");
    micButton.forceActiveFocus();input.keyPress(Qt.Key_Space);
    check(microphone.starts === 2,"keyboard hold did not record");
   } else if(stage === 3) {
    input.keyRelease(Qt.Key_Space);
    check(microphone.releases === 2 && microphone.running,"keyboard release did not play");
    mic.active=false;check(!microphone.running,"recording survived dismissal");
    mic.active=true;fake.nodes.mic.audio.muted=true;
   } else if(stage === 4) {
    check(!micButton.enabled,"muted default input can be tested");
    fake.nodes.mic.audio.muted=false;
    input.mousePress(micButton,micButton.width/2,micButton.height/2);
    input.mouseMove(micButton,-30,-30);
    input.mouseRelease(micButton,-30,-30);
    check(!microphone.running && microphone.releases === 2,"cancelled gesture played recording");
    window.pageWidth=288;window.implicitWidth=320;
   } else if(stage === 5) {
    check(micButton.width <= 288 && micButton.height > 0,"narrow footer overflow");
    capture("microphone-narrow.png");
   } else if(stage === 6) {
    console.log("AUDIO_PASS");Qt.quit();
   }
   stage++;
  } catch(error) {console.error("AUDIO_FAIL",error.message);Qt.quit();}
 } }
}
""".replace('FAKE_SERVICE', drawer_tests.FAKE_SERVICE)
            .replace('STATE', json.dumps(state))
            .replace('PREVIEW_DIR', json.dumps(os.environ.get('AUDIO_PREVIEW_DIR', '')))
        )


if __name__ == '__main__':
    unittest.main()
