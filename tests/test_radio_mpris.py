"""Real mpv/MPRIS controls in Sound, isolated from host audio and session bus."""

import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

import support
from test_audio_drawer import FAKE_SERVICE, stream
from test_radio import STATION

sys.path.insert(0, str(support.DESKTOP))
from spaces.radio.backend import RadioBackend

PLUGIN = Path('/usr/lib/mpv-mpris/mpris.so')


def session_check():
    """Called only inside dbus-run-session; real decoders use null audio output."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime = root / 'runtime'
        runtime.mkdir(mode=0o700)
        audio = root / 'fixture.wav'
        with wave.open(str(audio), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b'\0\0' * 8000 * 60)

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(
            ('127.0.0.1', 0), functools.partial(Handler, directory=str(root))
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}/fixture.wav'
        backend = RadioBackend(root / 'config', root / 'data', root / 'cache')
        original_popen = subprocess.Popen

        def null_player(argv, **kwargs):
            index = argv.index('--')
            return original_popen(argv[:index] + ['--ao=null'] + argv[index:], **kwargs)

        other = None
        try:
            with (
                patch.dict(os.environ, XDG_RUNTIME_DIR=str(runtime)),
                patch.object(subprocess, 'Popen', side_effect=null_player),
            ):
                backend.start(dict(station=STATION, url=url))
            other = original_popen(
                [
                    'mpv',
                    '--no-config',
                    '--no-video',
                    '--no-terminal',
                    '--really-quiet',
                    '--ao=null',
                    '--script=' + str(PLUGIN),
                    '--audio-client-name=mpv',
                    '--',
                    url,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            records = [
                stream('100', label='Radio', applicationBinary='mpv'),
                stream('101', label='mpv', applicationBinary='mpv'),
            ]
            state = dict(available=True, outputs=[], outputDevices=[], warning='')
            body = """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers"
ShellRoot {
 FloatingWindow {
  id:window;implicitWidth:480;implicitHeight:900;visible:true
  FAKE_SERVICE
  SoundDrawer {id:drawer;width:448;height:868;service:fake;active:true}
  TestCase {id:input;when:false;parent:window.contentItem}
  property int step:0
  property var radio:null
  property var other:null
  function check(value,message){if(!value)throw new Error(message);}
  function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=window.find(child,name);if(found)return found;}return null;}
  Timer {id:driver;interval:90;running:true;repeat:false;onTriggered:{try{
   if(window.step===0){
    window.radio=drawer.players.find(player=>player.identity==="Radio");
    window.other=drawer.players.find(player=>player.identity==="mpv");
    if(!window.radio||!window.other||!window.radio.canTogglePlaying)return;
    fake.streams=fake.attach(RECORDS,true);window.step++;return;
   }
   const name="audioPlayer:"+(window.radio?.dbusName || "");
   if(window.step===1){
    const radioControls=window.find(window.find(drawer,"appPlayback:100"),name);
    window.check(!!radioControls,"Radio controls did not attach to its row beside another mpv stream");
    window.check(drawer.playerAssignments.find(match=>match.player===window.other).key==="101","other mpv session attached to Radio");
    window.check(window.radio.isPlaying&&window.other.isPlaying,"real decoders not playing");
    const button=window.find(radioControls,name+":playPause");input.mouseClick(button,button.width/2,button.height/2);
    window.step++;return;
   }
   if(window.step===2){
    if(window.radio.isPlaying)return;
    window.check(window.other.isPlaying,"Radio pause affected another player");
    fake.streams=fake.streams.filter(record=>record.key!=="100");drawer.active=false;window.step++;return;
   }
   if(window.step===3){
    window.check(!window.radio.isPlaying,"drawer dismissal resumed Radio");drawer.active=true;
    window.step++;return;
   }
   if(window.step===4){
    const playback=window.find(drawer,"audioPlayback");
    window.check(playback.visible&&window.find(playback,name),"paused Radio lost controls when its audio stream disappeared");
    const button=window.find(playback,name+":playPause");input.mouseClick(button,button.width/2,button.height/2);
    window.step++;return;
   }
   if(window.step===5){
    if(!window.radio.isPlaying)return;
    window.check(window.other.isPlaying,"Radio resume affected another player");
    window.radio.stop();window.step++;return;
   }
   if(window.step===6){
    if(drawer.players.some(player=>player.identity==="Radio"))return;
    window.check(drawer.players.some(player=>player.identity==="mpv"),"Radio stop removed the other session");
    console.log("DISPLAY_PASS");Qt.quit();
   }
  }catch(error){console.error("DISPLAY_FAIL",error.message+" "+error.stack);Qt.quit();}finally{driver.restart();}}}
  Timer {interval:11000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout at "+window.step);Qt.quit();}}
 }
}""".replace('FAKE_SERVICE', FAKE_SERVICE.replace('STATE', json.dumps(state))).replace(
                'RECORDS', json.dumps(records)
            )
            case = unittest.TestCase()
            support.run_qml(case, body)
            for _ in range(100):
                if backend.player.poll() is not None:
                    break
                time.sleep(0.01)
            assert not backend.status()['playing'], 'MPRIS Stop did not stop Radio'
            print('RADIO_MPRIS_PASS')
        finally:
            backend.stop()
            if other and other.poll() is None:
                other.terminate()
                other.wait(timeout=3)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


@unittest.skipUnless(
    support.QS
    and shutil.which('mpv')
    and PLUGIN.exists()
    and shutil.which('dbus-run-session'),
    'Quickshell, mpv-mpris and a private D-Bus session are required',
)
class RadioMprisTests(unittest.TestCase):
    def test_sound_real_mpris_pause_resume_stop_and_distinct_mpv_sessions(self):
        result = subprocess.run(
            [
                'dbus-run-session',
                '--',
                sys.executable,
                str(Path(__file__).resolve()),
                '--session',
            ],
            env={
                **os.environ,
                'PYTHONDONTWRITEBYTECODE': '1',
                'PIPEWIRE_REMOTE': 'dotfiles-tests-unavailable',
            },
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RADIO_MPRIS_PASS', result.stdout)


if __name__ == '__main__':
    if sys.argv[1:] == ['--session']:
        session_check()
    else:
        unittest.main()
