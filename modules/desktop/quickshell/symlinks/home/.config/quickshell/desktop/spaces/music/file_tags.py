"""Bounded, versioned DAV range reads for embedded metadata, without caching audio."""

from http.client import HTTPException
import io
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request

from mutagen import File, MutagenError
from mutagen.oggopus import OggOpus

from spaces.music.records import MusicError
from spaces.music.remote_files import RemoteFiles
from spaces.music.tags import TAG_FORMATS, fields, format_summary


class RangeFile(io.RawIOBase):
    block_size = 65536
    byte_limit = 8 * 1024 * 1024
    request_limit = 128

    def __init__(self, remote, rel):
        self.dav = remote.dav
        self.url = remote.url('Music/' + rel)
        self.name = rel
        self.position = 0
        self.blocks = {}
        self.transferred = 0
        self.requests = 0
        self.deadline = time.monotonic() + 25
        with self.open('HEAD') as response:
            self.size = int(response.headers.get('Content-Length', '-1'))
            self.etag = response.headers.get('ETag', '')
        if self.size < 0 or not self.etag or self.etag.startswith('W/'):
            raise MusicError('Nextcloud did not provide a versioned file size.')

    def open(self, method, headers=None):
        if (
            time.monotonic() >= self.deadline
            or self.requests >= self.request_limit
            or not self.dav.allowed(self.url)
        ):
            raise MusicError(
                'The file tags could not be read within the preview limit.'
            )
        self.requests += 1
        try:
            return self.dav.opener.open(
                Request(
                    self.url,
                    method=method,
                    headers={
                        'Authorization': self.dav.auth,
                        'User-Agent': 'DesktopShell/1.0',
                        'Accept-Encoding': 'identity',
                        **(headers or {}),
                    },
                ),
                timeout=min(8, max(0.1, self.deadline - time.monotonic())),
            )
        except HTTPError as error:
            error.close()
            if error.code == 412:
                raise MusicError(
                    'The server song changed while reading its tags.'
                ) from None
            raise MusicError(
                'Nextcloud could not read the existing file tags.'
            ) from None
        except (URLError, OSError, HTTPException):
            raise MusicError(
                'Nextcloud is unreachable while reading file tags.'
            ) from None

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        if whence not in (0, 1, 2):
            raise ValueError('Invalid seek mode')
        position = (0, self.position, self.size)[whence] + offset
        if position < 0:
            raise ValueError('Invalid file position')
        self.position = position
        return position

    def read(self, size=-1):
        size = max(0, self.size - self.position) if size < 0 else size
        size = min(size, max(0, self.size - self.position))
        if size > self.byte_limit:
            raise MusicError('These file tags exceed the preview limit.')
        result = bytearray()
        while size:
            index, offset = divmod(self.position, self.block_size)
            if index not in self.blocks:
                start = index * self.block_size
                end = min(start + self.block_size, self.size) - 1
                length = end - start + 1
                if self.transferred + length > self.byte_limit:
                    raise MusicError('These file tags exceed the preview limit.')
                with self.open(
                    'GET',
                    {'Range': f'bytes={start}-{end}', 'If-Match': self.etag},
                ) as response:
                    # Never consume a full response when the server ignores Range.
                    if (
                        response.status != 206
                        or response.headers.get('Content-Range')
                        != f'bytes {start}-{end}/{self.size}'
                        or response.headers.get('ETag', self.etag) != self.etag
                        or response.headers.get('Content-Encoding', 'identity')
                        != 'identity'
                    ):
                        raise MusicError(
                            'Nextcloud could not provide a safe partial tag read.'
                        )
                    data = response.read(length + 1)
                    if len(data) != length:
                        raise MusicError('Nextcloud returned incomplete file tags.')
                self.transferred += length
                self.blocks[index] = data
            part = self.blocks[index][offset : offset + size]
            result.extend(part)
            self.position += len(part)
            size -= len(part)
        return bytes(result)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def read(song):
    from spaces.music import local_files, tags

    _, rel = local_files.checked(song)
    if path := local_files.cached(song):
        before = local_files.signature(path)
        result = tags.read(path, local_files.run)
        if local_files.signature(path) != before:
            raise MusicError('The local song changed while reading its tags.')
        result.update(signature=before)
    else:
        if Path(rel).suffix.lower() not in TAG_FORMATS | {'.wma', '.ape', '.wv'}:
            raise MusicError(
                'This format does not support partial metadata reads. Your edits can still be saved.'
            )
        try:
            with RangeFile(RemoteFiles(), rel) as stream:
                audio = File(stream)
                if audio is None:
                    raise MusicError(
                        'This format does not support partial metadata reads.'
                    )
                info = audio.info
                bits = int(getattr(info, 'bits_per_sample', 0) or 0)
                rate = int(
                    getattr(
                        info, 'sample_rate', 48000 if isinstance(audio, OggOpus) else 0
                    )
                    or 0
                )
                channels = int(getattr(info, 'channels', 0) or 0)
                bitrate = int(getattr(info, 'bitrate', 0) or 0)
                result = dict(
                    tags=fields(audio) if audio.tags is not None else {},
                    remoteVersion=stream.etag,
                    duration=float(getattr(info, 'length', 0) or 0),
                    sampleRate=rate,
                    bitDepth=bits,
                    fileInfo=format_summary(
                        Path(rel).suffix.lstrip('.'),
                        bits=bits,
                        rate=rate,
                        channels=channels,
                        bitrate=bitrate,
                    ),
                )
                with stream.open('HEAD', {'If-Match': stream.etag}) as response:
                    if response.headers.get('ETag') != stream.etag:
                        raise MusicError(
                            'The server song changed while reading its tags.'
                        )
        except (MutagenError, ValueError, OSError, HTTPException):
            raise MusicError(
                'The existing file tags could not be read. Your edits can still be saved.'
            ) from None
    result['knownFields'] = list(result['tags'])
    return result
