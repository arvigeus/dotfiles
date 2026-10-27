"""Music-owned lossless tag edits, verified before atomically replacing a cache file."""

import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from mutagen import MutagenError
from mutagen.oggopus import OggOpus

from spaces.music.records import MusicError

FIELDS = {
    'title': 'Title',
    'artist': 'Artist',
    'album': 'Album',
    'album_artist': 'Album artist',
    'date': 'Date',
    'track': 'Track / total',
    'disc': 'Disc / total',
    'genre': 'Genre',
    'composer': 'Composer',
    'comment': 'Comment',
    'lyrics': 'Lyrics',
}


def read(path, run):
    code, output = run(
        [
            'ffprobe',
            '-v',
            'error',
            '-show_format',
            '-show_streams',
            '-of',
            'json',
            str(path),
        ],
        20,
    )
    if code:
        raise MusicError('This audio file could not be read.')
    data = json.loads(output)
    audio = [s for s in data.get('streams', []) if s.get('codec_type') == 'audio']
    if not audio:
        raise MusicError('This file contains no audio.')
    tags = {k.lower(): str(v) for s in audio[:1] for k, v in s.get('tags', {}).items()}
    tags.update(
        {k.lower(): str(v) for k, v in data.get('format', {}).get('tags', {}).items()}
    )
    for key, alias in [
        ('album_artist', 'albumartist'),
        ('date', 'year'),
        ('track', 'tracknumber'),
        ('disc', 'discnumber'),
    ]:
        tags[key] = tags.get(key, tags.get(alias, ''))
    # FFmpeg exposes ID3's language-qualified lyrics as lyrics-eng.
    tags['lyrics'] = tags.get(
        'lyrics', next((v for k, v in tags.items() if k.startswith('lyrics-')), '')
    )
    duration = data.get('format', {}).get('duration') or audio[0].get('duration') or 0
    stream = audio[0]

    def integer(value):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    bits = integer(stream.get('bits_per_raw_sample')) or integer(
        stream.get('bits_per_sample')
    )
    rate = integer(stream.get('sample_rate'))
    channels = integer(stream.get('channels'))
    bitrate = integer(stream.get('bit_rate') or data.get('format', {}).get('bit_rate'))
    summary = [
        Path(path).suffix.lstrip('.').upper() or stream.get('codec_name', '').upper()
    ]
    if bits:
        summary.append(str(bits) + '-bit')
    elif bitrate:
        summary.append(str(round(bitrate / 1000)) + ' kbps')
    if rate:
        summary.append(f'{rate / 1000:g} kHz')
    if channels:
        summary.append(
            {1: 'Mono', 2: 'Stereo'}.get(channels, str(channels) + ' channels')
        )
    covers = [
        s.get('index')
        for s in data.get('streams', [])
        if s.get('disposition', {}).get('attached_pic')
    ]
    return dict(
        tags={k: tags.get(k, '') for k in FIELDS},
        duration=float(duration),
        codec=stream.get('codec_name', ''),
        sampleRate=stream.get('sample_rate', ''),
        bitDepth=bits,
        fileInfo=' · '.join(filter(None, summary)),
        coverIndexes=covers,
    )


def write(path, changes, run, signature, register, unregister, artwork=None):
    if (
        not isinstance(changes, dict)
        or set(changes) - FIELDS.keys()
        or any(
            not isinstance(v, str) or '\0' in v or len(v) > 200000
            for v in changes.values()
        )
    ):
        raise MusicError('Invalid tag changes.')
    path = Path(path)
    image = None
    if artwork is not None:
        from urllib.parse import unquote, urlsplit

        if path.suffix.lower() not in ('.mp3', '.flac', '.m4a', '.mp4'):
            raise MusicError('Cover editing supports MP3, FLAC and M4A files.')
        parsed = urlsplit(str(artwork))
        if parsed.scheme not in ('', 'file') or parsed.netloc not in ('', 'localhost'):
            raise MusicError('Choose a local image file.')
        image = Path(unquote(parsed.path) if parsed.scheme else str(artwork)).resolve(
            strict=True
        )
        if not image.is_file() or image.stat().st_size > 20 * 1024 * 1024:
            raise MusicError('Choose an image smaller than 20 MiB.')
        code, output = run(
            [
                'ffprobe',
                '-v',
                'error',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=width,height',
                '-of',
                'json',
                str(image),
            ],
            20,
        )
        if code or not json.loads(output).get('streams'):
            raise MusicError('The selected file could not be read as an image.')
        image_signature = signature(image)
    before = signature(path)
    fd, name = tempfile.mkstemp(
        prefix='.music-tags-', suffix=path.suffix, dir=path.parent
    )
    os.close(fd)
    temporary = Path(name)
    register(temporary)
    try:
        command = ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(path)]
        previous = read(path, run) if image else None
        if image:
            command += ['-i', str(image)]
        command += [
            '-map',
            '0',
            '-map_metadata',
            '0',
            '-map_chapters',
            '0',
            '-c',
            'copy',
        ]
        if image:
            for index in previous['coverIndexes']:
                command += ['-map', '-0:' + str(index)]
            command += [
                '-map',
                '1:v:0',
                '-c:v',
                'mjpeg',
                '-disposition:v',
                'attached_pic',
                '-metadata:s:v',
                'title=Cover',
                '-metadata:s:v',
                'comment=Cover (front)',
            ]
        for key, value in changes.items():
            command += ['-metadata', key + '=' + value]
            if path.suffix.lower() in ('.mka', '.mkv', '.ogg', '.opus'):
                command += ['-metadata:s:a:0', key + '=' + value]
        if path.suffix.lower() == '.opus':
            # Keep Ogg picture comments and audio packets intact when editing tags.
            shutil.copyfile(path, temporary)
            try:
                audio = OggOpus(temporary)
                for key, value in changes.items():
                    audio[key] = value
                audio.save()
            except MutagenError:
                raise MusicError(
                    'The Opus tags could not be saved. The original song was kept.'
                ) from None
        elif run(command + [str(temporary)])[0]:
            raise MusicError(
                'This format could not save the tags. The original song was kept.'
            )
        checked = read(temporary, run)
        if image and (
            not checked['coverIndexes'] or signature(image) != image_signature
        ):
            raise MusicError(
                'The cover could not be saved safely. The original song was kept.'
            )
        actual = checked['tags']
        if any(actual.get(key, '') != value for key, value in changes.items()):
            raise MusicError(
                'This format could not preserve every tag edit. The original song was kept.'
            )
        if signature(path) != before:
            raise MusicError(
                'The local song changed while saving. Reload its information.'
            )
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
        unregister(temporary)
