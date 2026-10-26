"""Authenticated provider streams keep secrets out of replies and process argv."""
from contextlib import ExitStack
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import io
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
import sys
import support
sys.path.insert(0, str(support.DESKTOP))
from spaces.music import backend
from spaces.music.cloud_stream import StreamBroker,ProviderSession
from integrations.subsonic import MusicError


class ProviderReferenceTests(unittest.TestCase):
    def test_playlists_cannot_open_local_files_or_other_protocols(self):
        session=ProviderSession('https://provider.example/stream',{},'http://127.0.0.1:1234/ticket')
        for target in ('file:///private/song.flac','data:audio/flac;base64,AAAA','ftp://provider.example/song.flac'):
            with self.subTest(target=target):
                response=io.BytesIO(('#EXTM3U\n'+target+'\n').encode());response.geturl=lambda:'https://provider.example/stream.m3u8'
                with self.assertRaises(MusicError):session.manifest(response,'application/vnd.apple.mpegurl')
                with self.assertRaises(MusicError):session.open(target,{})


class ProviderStreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.requests=[];case=self
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','anullsrc','-t','0.6','-c:a','aac','-f','hls','-hls_time','0.2','-hls_segment_filename',str(self.root/'segment%d.ts'),str(self.root/'entry.m3u8')],check=True)
        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                case.requests.append((self.path,self.headers.get('Authorization')))
                if self.headers.get('Authorization')!='Bearer fixture-header-secret,with-comma':self.send_error(403);return
                super().do_GET()
            def log_message(self,*_):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(self.root)))
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.broker=StreamBroker();self.addCleanup(self.broker.close)
        self.url=f'http://127.0.0.1:{self.server.server_port}/entry.m3u8?token=fixture-url-secret'
        self.headers={'Authorization':'Bearer fixture-header-secret,with-comma'}
        self.song=dict(id='one',kind='song',source='apple',title='Title',artist='Artist',album='Album',releaseDate='2020-01-01')
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(backend,'STREAMS',self.broker))
        self.stack.enter_context(patch.object(backend,'DATA',self.root/'data'))
        self.stack.enter_context(patch.object(backend.player_ipc,'directory',return_value=self.root))
        self.stack.enter_context(patch.object(backend,'resolve_track',return_value={'url':self.url,'headers':self.headers}))
    def assert_private(self, value):
        serialized=json.dumps(value)
        self.assertNotIn('fixture-url-secret',serialized)
        self.assertNotIn('fixture-header-secret',serialized)
        self.assertNotIn('Authorization',serialized)
    def test_real_mpv_plays_authenticated_hls_without_secrets_in_command(self):
        result=backend.start_player(dict(track=self.song))
        self.assert_private(result)
        result['command'].insert(1,'--ao=null')
        process=subprocess.run(result['command'],capture_output=True,timeout=8)
        self.assertEqual(process.returncode,0)
        self.assertGreaterEqual(len(self.requests),2)
        self.assertTrue(all(auth==self.headers['Authorization'] for _,auth in self.requests))
        public_url=result['command'][-1];backend.cleanup_player(dict(ipcPath=result['ipcPath']))
        with self.assertRaises(HTTPError) as error:urlopen(public_url,timeout=1)
        error.exception.close()
    def test_real_ffmpeg_downloads_authenticated_hls_without_secrets_in_argv(self):
        real_popen=subprocess.Popen
        with patch.object(backend.subprocess,'Popen',wraps=real_popen) as start:
            path=backend.save_stream_track(self.song,{'headers':self.headers},self.root/'Music')
        self.assert_private(start.call_args.args[0])
        self.assertTrue(Path(path).is_file())
        self.assertGreaterEqual(len(self.requests),2)
        self.assertTrue(all(auth==self.headers['Authorization'] for _,auth in self.requests))
        self.assertEqual(self.broker.tickets,{})
    def test_manifest_references_are_revoked_with_the_main_ticket(self):
        url=self.broker.provider_url(self.url,self.headers);self.broker.bind('fixture',url)
        with urlopen(url,timeout=2) as reply:body=reply.read().decode()
        self.assert_private(body)
        child=next(line for line in body.splitlines() if line and not line.startswith('#'))
        with urlopen(child,timeout=2) as reply:self.assertTrue(reply.read())
        self.broker.release('fixture')
        with self.assertRaises(HTTPError) as error:urlopen(child,timeout=1)
        error.exception.close()

    def test_real_ffmpeg_downloads_authenticated_dash_templates(self):
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','anullsrc','-t','0.6','-c:a','aac','-f','dash','-seg_duration','0.2',str(self.root/'entry.mpd')],check=True)
        with patch.object(backend,'resolve_track',return_value={'url':self.url.replace('entry.m3u8','entry.mpd'),'headers':self.headers}):
            path=backend.save_stream_track(self.song,{'headers':self.headers},self.root/'Music')
        self.assertTrue(Path(path).is_file())
        self.assertTrue(any('.m4s' in url for url,_ in self.requests))
        self.assertTrue(all(auth==self.headers['Authorization'] for _,auth in self.requests))
