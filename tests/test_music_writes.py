"""Real HTTP conditional writes reject changes made after the client preflight."""

from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import subprocess
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
from spaces.music import file_tags


class ConditionalWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'song.flac'
        self.path.write_bytes(b'local edited song')
        self.files = {'Music/song.flac': (b'original server song', '"v1"')}
        self.requests = []
        self.after_copy = None
        self.before_put = None
        self.before_range = None
        self.range_status = 206
        self.bad_range = False
        self.bytes_read = 0
        case = self
        prefix = '/remote.php/dav/files/alice/'

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def key(self):
                return unquote(self.path.removeprefix(prefix))

            def respond(self, status, body=b'', etag=''):
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                if etag:
                    self.send_header('ETag', etag)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_HEAD(self):
                content, etag = case.files[self.key()]
                self.send_response(200)
                self.send_header('Content-Length', str(len(content)))
                self.send_header('ETag', etag)
                self.end_headers()

            def do_GET(self):
                case.requests.append(('GET', dict(self.headers)))
                if case.before_range:
                    case.before_range()
                content, etag = case.files[self.key()]
                if self.headers.get('If-Match') != etag:
                    self.respond(412)
                    return
                match = re.fullmatch(
                    r'bytes=(\d+)-(\d+)', self.headers.get('Range', '')
                )
                start, end = map(int, match.groups())
                body = content[start : end + 1] if case.range_status == 206 else content
                self.send_response(case.range_status)
                self.send_header('Content-Length', str(len(body)))
                self.send_header(
                    'Content-Range',
                    'invalid'
                    if case.bad_range
                    else f'bytes {start}-{end}/{len(content)}',
                )
                self.send_header('ETag', etag)
                self.end_headers()
                case.bytes_read += len(body)
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_MKCOL(self):
                self.respond(201)

            def do_PROPFIND(self):
                item = case.files.get(self.key())
                if not item:
                    self.respond(404)
                    return
                self.respond(
                    207,
                    (
                        '<d:multistatus xmlns:d="DAV:"><d:getetag>'
                        + item[1]
                        + '</d:getetag></d:multistatus>'
                    ).encode(),
                )

            def do_COPY(self):
                current = case.files.get(self.key())
                case.requests.append(('COPY', dict(self.headers)))
                if not current or self.headers.get('If-Match') != current[1]:
                    self.respond(412)
                    return
                target = unquote(self.headers['Destination'].split(prefix, 1)[1])
                if target in case.files:
                    self.respond(412)
                    return
                case.files[target] = current
                if case.after_copy:
                    case.after_copy()
                self.respond(201)

            def do_PUT(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                case.requests.append(('PUT', dict(self.headers)))
                if case.before_put:
                    case.before_put()
                current = case.files.get(self.key())
                if self.headers.get('If-None-Match') == '*' and current:
                    self.respond(412)
                    return
                if self.headers.get('If-Match') and (
                    not current or current[1] != self.headers['If-Match']
                ):
                    self.respond(412)
                    return
                case.files[self.key()] = (body, '"v2"')
                self.respond(201, etag='"v2"')

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        origin = 'http://127.0.0.1:' + str(self.server.server_port)

        class Loopback:
            def open(self, request, timeout):
                return urlopen(
                    Request(
                        request.full_url.replace('https://cloud.example', origin),
                        data=request.data,
                        method=request.method,
                        headers=dict(request.headers),
                    ),
                    timeout=timeout,
                )

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            patch.object(nextcloud, 'app_password', return_value='fixture-password')
        )
        account = dict(url='https://cloud.example/', username='alice')
        self.remote = RemoteFiles.__new__(RemoteFiles)
        self.remote.dav = nextcloud.DAVClient(account, scope=prefix, opener=Loopback())

    def test_partial_tag_reads_load_comments_lyrics_and_format_without_caching_audio(
        self,
    ):
        for extension in ('flac', 'mp3', 'm4a', 'ogg', 'opus'):
            with self.subTest(extension=extension):
                path = self.path.with_suffix('.' + extension)
                subprocess.run(
                    [
                        'ffmpeg',
                        '-v',
                        'error',
                        '-y',
                        '-f',
                        'lavfi',
                        '-i',
                        'anoisesrc=r=48000',
                        '-t',
                        '30',
                        '-metadata',
                        'title=File title',
                        '-metadata',
                        'comment=File comment',
                        '-metadata',
                        'lyrics=Embedded lyrics',
                        str(path),
                    ],
                    check=True,
                )
                payload = path.read_bytes()
                self.files['Music/' + path.name] = (payload, '"v1"')
                self.bytes_read = 0
                with (
                    patch(
                        'spaces.music.local_files.checked',
                        return_value=('fixture', path.name),
                    ),
                    patch('spaces.music.local_files.cached', return_value=None),
                    patch.object(file_tags, 'RemoteFiles', return_value=self.remote),
                ):
                    result = file_tags.read({'source': 'nextcloud'})
                self.assertEqual(result['tags']['title'], 'File title')
                self.assertEqual(result['tags']['comment'], 'File comment')
                self.assertEqual(result['tags']['lyrics'], 'Embedded lyrics')
                self.assertIn('lyrics', result['knownFields'])
                self.assertEqual(result['sampleRate'], 48000)
                self.assertIn('48 kHz', result['fileInfo'])
                self.assertGreater(result['duration'], 29)
                if extension == 'flac':
                    self.assertGreater(result['bitDepth'], 0)
                self.assertEqual(result['remoteVersion'], '"v1"')
                self.assertLess(self.bytes_read, len(payload))

    def test_range_reader_rejects_ignored_or_malformed_ranges_without_reading_body(
        self,
    ):
        self.files['Music/song.flac'] = (b'x' * 100000, '"v1"')
        for status, bad in ((200, False), (206, True)):
            self.range_status, self.bad_range = status, bad
            with file_tags.RangeFile(self.remote, 'song.flac') as stream:
                with self.assertRaises(file_tags.MusicError):
                    stream.read(1)
                self.assertEqual(stream.transferred, 0)

    def test_range_reader_rejects_versions_changes_and_excessive_reads(self):
        with file_tags.RangeFile(self.remote, 'song.flac') as stream:
            self.before_range = lambda: self.files.update(
                {'Music/song.flac': (b'new file', '"v2"')}
            )
            with self.assertRaisesRegex(file_tags.MusicError, 'changed'):
                stream.read(1)
        self.before_range = None
        with file_tags.RangeFile(self.remote, 'song.flac') as stream:
            stream.byte_limit = 1
            with self.assertRaisesRegex(file_tags.MusicError, 'limit'):
                stream.read(2)

    def test_update_streams_bytes_and_retains_the_previous_version(self):
        self.assertEqual(self.remote.etag('song.flac'), '"v1"')
        self.assertEqual(
            self.remote.upload(self.path, 'song.flac', '"v1"', 'history'), '"v2"'
        )
        self.assertEqual(self.files['Music/song.flac'][0], self.path.read_bytes())
        self.assertEqual(
            self.files['Music-history/history/song.flac'][0], b'original server song'
        )
        self.assertEqual(self.requests[-1][1]['If-Match'], '"v1"')

    def test_concurrent_update_after_backup_is_rejected_without_replacing_it(self):
        self.after_copy = lambda: self.files.update(
            {'Music/song.flac': (b'concurrent server edit', '"concurrent"')}
        )
        with self.assertRaisesRegex(nextcloud.NextcloudError, 'changed'):
            self.remote.upload(self.path, 'song.flac', '"v1"', 'history')
        self.assertEqual(self.files['Music/song.flac'][0], b'concurrent server edit')
        self.assertEqual(
            self.files['Music-history/history/song.flac'][0], b'original server song'
        )
        self.assertEqual(self.path.read_bytes(), b'local edited song')

    def test_concurrent_create_is_rejected_without_overwriting_the_new_file(self):
        self.before_put = lambda: self.files.update(
            {'Music/new.flac': (b'another uploader', '"concurrent"')}
        )
        with self.assertRaisesRegex(nextcloud.NextcloudError, 'changed'):
            self.remote.upload(self.path, 'new.flac', None, 'history')
        self.assertEqual(self.files['Music/new.flac'][0], b'another uploader')
        self.assertEqual(self.requests[-1][1]['If-None-Match'], '*')
