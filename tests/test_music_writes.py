"""Real HTTP conditional writes reject changes made after the client preflight."""
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import unquote
from urllib.request import Request, urlopen
import sys
import support
sys.path.insert(0, str(support.DESKTOP))
from integrations import nextcloud
from spaces.music.remote_files import RemoteFiles


class ConditionalWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'song.flac';self.path.write_bytes(b'local edited song')
        self.files = {'Music/song.flac': (b'original server song', '"v1"')}
        self.requests = [];self.after_copy = None;self.before_put = None
        case = self
        prefix = '/remote.php/dav/files/alice/'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):pass
            def key(self):return unquote(self.path.removeprefix(prefix))
            def respond(self, status, body=b'', etag=''):
                self.send_response(status);self.send_header('Content-Length', str(len(body)))
                if etag:self.send_header('ETag', etag)
                self.end_headers();self.wfile.write(body)
            def do_MKCOL(self):self.respond(201)
            def do_PROPFIND(self):
                item=case.files.get(self.key())
                if not item:self.respond(404);return
                self.respond(207,('<d:multistatus xmlns:d="DAV:"><d:getetag>'+item[1]+'</d:getetag></d:multistatus>').encode())
            def do_COPY(self):
                current=case.files.get(self.key());case.requests.append(('COPY', dict(self.headers)))
                if not current or self.headers.get('If-Match')!=current[1]:self.respond(412);return
                target=unquote(self.headers['Destination'].split(prefix,1)[1])
                if target in case.files:self.respond(412);return
                case.files[target]=current
                if case.after_copy:case.after_copy()
                self.respond(201)
            def do_PUT(self):
                body=self.rfile.read(int(self.headers['Content-Length']));case.requests.append(('PUT', dict(self.headers)))
                if case.before_put:case.before_put()
                current=case.files.get(self.key())
                if self.headers.get('If-None-Match')=='*' and current:self.respond(412);return
                if self.headers.get('If-Match') and (not current or current[1]!=self.headers['If-Match']):self.respond(412);return
                case.files[self.key()]=(body,'"v2"');self.respond(201,etag='"v2"')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        origin='http://127.0.0.1:'+str(self.server.server_port)
        class Loopback:
            def open(self,request,timeout):
                return urlopen(Request(request.full_url.replace('https://cloud.example',origin),data=request.data,method=request.method,headers=dict(request.headers)),timeout=timeout)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(nextcloud,'app_password',return_value='fixture-password'))
        account=dict(url='https://cloud.example/',username='alice')
        self.remote=RemoteFiles.__new__(RemoteFiles)
        self.remote.dav=nextcloud.DAVClient(account,scope=prefix,opener=Loopback())
    def test_update_streams_bytes_and_retains_the_previous_version(self):
        self.assertEqual(self.remote.etag('song.flac'),'"v1"')
        self.assertEqual(self.remote.upload(self.path,'song.flac','"v1"','history'),'"v2"')
        self.assertEqual(self.files['Music/song.flac'][0],self.path.read_bytes())
        self.assertEqual(self.files['Music-history/history/song.flac'][0],b'original server song')
        self.assertEqual(self.requests[-1][1]['If-Match'],'"v1"')
    def test_concurrent_update_after_backup_is_rejected_without_replacing_it(self):
        self.after_copy=lambda:self.files.update({'Music/song.flac':(b'concurrent server edit','"concurrent"')})
        with self.assertRaisesRegex(nextcloud.NextcloudError,'changed'):
            self.remote.upload(self.path,'song.flac','"v1"','history')
        self.assertEqual(self.files['Music/song.flac'][0],b'concurrent server edit')
        self.assertEqual(self.files['Music-history/history/song.flac'][0],b'original server song')
        self.assertEqual(self.path.read_bytes(),b'local edited song')
    def test_concurrent_create_is_rejected_without_overwriting_the_new_file(self):
        self.before_put=lambda:self.files.update({'Music/new.flac':(b'another uploader','"concurrent"')})
        with self.assertRaisesRegex(nextcloud.NextcloudError,'changed'):
            self.remote.upload(self.path,'new.flac',None,'history')
        self.assertEqual(self.files['Music/new.flac'][0],b'another uploader')
        self.assertEqual(self.requests[-1][1]['If-None-Match'],'*')
