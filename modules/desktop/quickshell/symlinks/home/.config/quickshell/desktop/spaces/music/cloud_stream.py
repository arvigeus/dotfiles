"""Revocable loopback streams; credentials and provider URLs stay in Python."""
import hashlib
import re
import secrets
import socket
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from urllib.error import HTTPError
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, urlopen

from integrations.subsonic import MusicError
from spaces.music.cloud import LibraryClient, identity


class ProviderSession:
    def __init__(self, url, headers, base):
        self.url = url
        self.headers = dict(headers)
        self.base = base
        self.references = {}
        self.lock = threading.Lock()

    def reference(self, url, directory=False):
        self.validate_url(url)
        key = hashlib.sha256(url.encode()).hexdigest()
        suffix = PurePosixPath(urlsplit(url).path).suffix.lower()
        if not directory and re.fullmatch(r'\.[a-z0-9]{1,8}', suffix):
            key += suffix
        with self.lock:
            if len(self.references) >= 16384 and key not in self.references:
                raise MusicError('The provider playlist contains too many references.')
            self.references[key] = url
        return self.base + '/' + key + ('/' if directory else '')

    def resolve(self, path):
        suffix = path[len(urlsplit(self.base).path):]
        if not suffix:
            return self.url
        key, _, tail = suffix.lstrip('/').partition('/')
        with self.lock:
            url = self.references.get(key)
        if url is None:
            return None
        return urljoin(url, tail) if tail else url

    def open(self, url, extra):
        self.validate_url(url)
        headers = {key.lower(): value for key, value in self.headers.items()}
        for key, value in extra.items():
            if key.lower() == 'range' or key.lower() not in headers:
                headers[key.lower()] = value
        return urlopen(Request(url, headers=headers), timeout=15)

    @staticmethod
    def validate_url(url):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or any(char in url for char in '\r\n\0'):
            raise MusicError('The provider playlist contains an unsupported media URL.')

    def manifest(self, response, content_type):
        data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise MusicError('The provider playlist is too large.')
        base = response.geturl()
        if 'dash+xml' in content_type:
            root = ET.fromstring(data)
            namespace = root.tag.rsplit('}', 1)[0] + '}' if '}' in root.tag else ''
            if namespace:
                ET.register_namespace('', namespace[1:-1])
            base_element = root.find(namespace + 'BaseURL')
            if base_element is None:
                base_element = ET.Element(namespace + 'BaseURL')
                root.insert(0, base_element)
            base_element.text = urljoin(base, (base_element.text or '.').strip())
            for element in root.iter():
                if element.tag == namespace + 'BaseURL':
                    value = (element.text or '').strip()
                    element.text = self.reference(value, value.endswith('/')) if urlsplit(value).scheme else value
                for key in ('media', 'initialization', 'sourceURL'):
                    url = element.get(key, '')
                    if urlsplit(url).scheme:
                        directory = urljoin(url, '.')
                        element.set(key, self.reference(directory, True) + url[len(directory):])
            return ET.tostring(root, encoding='utf-8', xml_declaration=True)
        lines = []
        for line in data.decode('utf-8-sig').splitlines():
            if line.startswith('#'):
                line = re.sub(r'URI="([^"]+)"', lambda match: 'URI="' + self.reference(urljoin(base, match[1])) + '"', line)
            elif line.strip():
                line = self.reference(urljoin(base, line.strip()))
            lines.append(line)
        return ('\n'.join(lines) + '\n').encode()


class StreamBroker:
    def __init__(self, client_factory=LibraryClient):
        self.client_factory = client_factory
        self.lock = threading.Lock()
        self.tickets = {}
        self.responses = {}
        self.paths = {}
        self.server = None
        self.thread = None

    def start(self):
        if self.server:
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                path = '/' + self.path.lstrip('/').split('/', 1)[0]
                with owner.lock:
                    entry = owner.tickets.get(path)
                if not entry:
                    self.send_error(404)
                    return
                upstream = None
                try:
                    headers = {'Accept': 'audio/*'}
                    if self.headers.get('Range'):
                        headers['Range'] = self.headers['Range']
                    if isinstance(entry, ProviderSession):
                        target = entry.resolve(self.path)
                        if target is None:
                            self.send_error(404)
                            return
                        upstream = entry.open(target, headers)
                    else:
                        if self.path != path:
                            self.send_error(404)
                            return
                        client, track = entry
                        upstream = client.open('stream', {'id': track, 'format': 'raw'}, headers)
                    content_type = str(upstream.headers.get('Content-Type', '')).lower()
                    manifest = None
                    if isinstance(entry, ProviderSession):
                        suffix = urlsplit(upstream.geturl()).path.lower()
                        if suffix.endswith('.m3u8'):content_type = 'application/vnd.apple.mpegurl'
                        elif suffix.endswith('.mpd'):content_type = 'application/dash+xml'
                    if isinstance(entry, ProviderSession) and ('mpegurl' in content_type or 'dash+xml' in content_type):
                        manifest = entry.manifest(upstream, content_type)
                    elif not content_type.startswith(('audio/', 'application/octet-stream', 'video/')) and not (
                        isinstance(entry, ProviderSession) and (content_type.startswith('text/vtt') or
                        urlsplit(upstream.geturl()).path.lower().endswith(('.ts', '.m4s', '.aac', '.mp4', '.m4a', '.mp3', '.ogg', '.opus', '.wav', '.flac', '.webm')))):
                        self.send_error(502)
                        return
                    with owner.lock:
                        if owner.tickets.get(path) is not entry:
                            self.send_error(404)
                            return
                        owner.responses[upstream] = path
                    self.send_response(upstream.status)
                    for key in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges'):
                        if manifest is not None and key != 'Content-Type':
                            continue
                        if value := upstream.headers.get(key):
                            self.send_header(key, value)
                    if manifest is not None:
                        self.send_header('Content-Length', str(len(manifest)))
                    self.end_headers()
                    if manifest is not None:
                        self.wfile.write(manifest)
                    else:
                        while chunk := upstream.read(128 * 1024):
                            self.wfile.write(chunk)
                except HTTPError as error:
                    error.close()
                    self.send_error(416 if error.code == 416 else 502)
                except (OSError, ValueError):
                    self.close_connection = True
                finally:
                    if upstream:
                        with owner.lock:
                            owner.responses.pop(upstream, None)
                        upstream.close()

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        self.thread.start()

    def url(self, item):
        client = self.client_factory()
        if item.get('account') != client.account_id:
            raise MusicError('Refresh My Library before playing an item from another account.')
        track = identity(item.get('id'))
        with self.lock:
            self.start()
            path = '/' + secrets.token_urlsafe(24)
            self.tickets[path] = (client, track)
            return f'http://127.0.0.1:{self.server.server_port}{path}'

    def provider_url(self, url, headers):
        parsed = urlsplit(url)
        if parsed.scheme not in ('https', 'http') or not parsed.netloc or any(c in url for c in '\r\n\0'):
            raise MusicError('The provider returned an invalid stream URL.')
        with self.lock:
            self.start()
            path = '/' + secrets.token_urlsafe(24)
            base = f'http://127.0.0.1:{self.server.server_port}{path}'
            self.tickets[path] = ProviderSession(url, headers, base)
            return base

    def bind(self, ipc, url):
        with self.lock:
            self.paths[str(ipc)] = urlsplit(url).path

    @staticmethod
    def close_response(response):
        try:
            response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError):
            pass
        response.close()

    def release(self, ipc):
        with self.lock:
            path = self.paths.pop(str(ipc), None)
            self.tickets.pop(path, None)
            responses = [response for response, ticket in self.responses.items() if ticket == path]
        for response in responses:
            self.close_response(response)

    def close(self):
        with self.lock:
            self.tickets.clear()
            self.paths.clear()
            responses = list(self.responses)
        for response in responses:
            self.close_response(response)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
