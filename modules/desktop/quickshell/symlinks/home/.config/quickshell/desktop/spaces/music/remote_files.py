"""Conditional DAV writes. Server versions are checked at the commit itself."""
from pathlib import PurePosixPath
from urllib.parse import quote
import xml.etree.ElementTree as ET

from integrations import nextcloud
from spaces.books.jobs import check_cancelled, progress
from spaces.music.records import MusicError


class UploadBody:
    def __init__(self, stream):
        self.stream = stream
        self.total = stream.seek(0, 2)
        stream.seek(0)
        self.done = 0

    def read(self, size=-1):
        if self.done >= self.total:
            return b''
        check_cancelled()
        data = self.stream.read(size)
        self.done += len(data)
        progress(done=self.done, total=self.total, unit='bytes', detail='Uploading to Nextcloud…')
        return data


class RemoteFiles:
    def __init__(self):
        account = nextcloud.load_account()
        if not account:
            raise MusicError('Restore the shared Nextcloud account first.')
        self.dav = nextcloud.DAVClient(
            account, scope='remote.php/dav/files/' + quote(account['username'], safe='') + '/')

    def url(self, path):
        parts = PurePosixPath(path).parts
        if not parts or any(part in ('/', '.', '..') for part in parts):
            raise MusicError('Invalid server file path.')
        return self.dav.home + '/'.join(quote(part, safe='') for part in parts)

    def etag(self, rel):
        body = b'<d:propfind xmlns:d="DAV:"><d:prop><d:getetag/></d:prop></d:propfind>'
        document, _ = self.dav.request('PROPFIND', self.url('Music/' + rel), body,
                                       {'Depth': '0', 'Content-Type': 'application/xml'})
        value = ET.fromstring(document).findtext('.//{DAV:}getetag')
        if not value or value.startswith('W/') or any(c in value for c in '\r\n'):
            raise MusicError('The server did not provide a safe file version.')
        return value

    def parents(self, path):
        for parent in reversed(PurePosixPath(path).parents):
            if str(parent) == '.':
                continue
            url = self.url(str(parent)) + '/'
            try:
                self.dav.request('MKCOL', url)
            except nextcloud.NextcloudError:
                self.dav.request('PROPFIND', url, headers={'Depth': '0'})

    def upload(self, path, rel, expected, history):
        destination = self.url('Music/' + rel)
        self.parents('Music/' + rel)
        if expected:
            backup = 'Music-history/' + history + '/' + rel
            self.parents(backup)
            # COPY retains the source and its ETag. Moving it away before PUT
            # would make an If-Match precondition impossible to enforce.
            self.dav.request('COPY', destination, headers={
                'Destination': self.url(backup), 'Overwrite': 'F', 'If-Match': expected})
        check_cancelled()
        headers = {'Content-Type': 'application/octet-stream',
                   'Content-Length': str(path.stat().st_size),
                   'X-OC-Mtime': str(int(path.stat().st_mtime))}
        headers.update({'If-Match': expected} if expected else {'If-None-Match': '*'})
        with path.open('rb') as stream:
            _, response = self.dav.request('PUT', destination, UploadBody(stream), headers)
        return response.get('ETag') or response.get('Etag') or ''
