"""Music-owned lossless tag edits, verified before atomically replacing a cache file."""

import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from mutagen import File, MutagenError
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, Frames, ID3, COMM, USLT, PictureType
from mutagen.mp4 import MP4Cover, MP4Tags

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

ID3_FIELDS = {
    'title': 'TIT2',
    'artist': 'TPE1',
    'album': 'TALB',
    'album_artist': 'TPE2',
    'date': 'TDRC',
    'track': 'TRCK',
    'disc': 'TPOS',
    'genre': 'TCON',
    'composer': 'TCOM',
    'comment': 'COMM',
    'lyrics': 'USLT',
}

ID3_TEXT_ALIASES = {
    'album_artist': ('album_artist', 'albumartist', 'album artist'),
    'date': ('date', 'year'),
    'track': ('track', 'tracknumber'),
    'disc': ('disc', 'discnumber'),
    'lyrics': ('lyrics', 'uslt', 'unsyncedlyrics'),
}

MP4_FIELDS = {
    'title': '©nam',
    'artist': '©ART',
    'album': '©alb',
    'album_artist': 'aART',
    'date': '©day',
    'track': 'trkn',
    'disc': 'disk',
    'genre': '©gen',
    'composer': '©wrt',
    'comment': '©cmt',
    'lyrics': '©lyr',
}

TAG_FORMATS = {'.mp3', '.flac', '.m4a', '.mp4', '.ogg', '.opus'}
COVER_FORMATS = {'.mp3', '.flac', '.m4a', '.mp4'}


def text(value):
    if value is None:
        return ''
    if isinstance(value, (list, tuple)):
        return '; '.join(map(str, value))
    return str(value)


def fields(audio):
    tags = audio.tags
    if isinstance(tags, ID3):
        names = ID3_FIELDS
        result = {}
        for key, name in names.items():
            frame = next(iter(tags.getall(name)), None)
            if frame is None:
                frame = next(
                    (
                        value
                        for value in tags.getall('TXXX')
                        if value.desc.casefold() in ID3_TEXT_ALIASES.get(key, (key,))
                    ),
                    None,
                )
            result[key] = text(getattr(frame, 'text', frame))
        return result
    if isinstance(tags, MP4Tags):
        names = MP4_FIELDS
        result = {key: text(tags.get(name)) for key, name in names.items()}
        for key in ('track', 'disc'):
            value = tags.get(names[key])
            result[key] = (
                '/'.join(map(str, value[0]))
                if value and value[0][1]
                else str(value[0][0])
                if value
                else ''
            )
        return result
    values = {key.lower(): value for key, value in (tags or {}).items()}
    aliases = {
        'album_artist': ('albumartist', 'album artist', 'wm/albumartist'),
        'date': ('year', 'wm/year'),
        'track': ('tracknumber', 'wm/tracknumber'),
        'disc': ('discnumber', 'wm/partofset'),
        'artist': ('author',),
        'album': ('wm/albumtitle',),
        'genre': ('wm/genre',),
        'composer': ('wm/composer',),
        'comment': ('description',),
        'lyrics': ('unsyncedlyrics', 'wm/lyrics'),
    }
    result = {
        key: text(
            next(
                (
                    values[name]
                    for name in (key, *aliases.get(key, ()))
                    if name in values
                ),
                None,
            )
        )
        for key in FIELDS
    }
    for key in ('track', 'disc'):
        total = text(values.get(key + 'total') or values.get('total' + key + 's'))
        if total and result[key] and '/' not in result[key]:
            result[key] += '/' + total
    return result


def update_tags(path, changes):
    """Change only requested tags; keep custom frames, pictures and audio bytes."""
    audio = File(path)
    if audio is None:
        raise MusicError('This file has no supported tag container.')
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    if isinstance(tags, ID3):
        names = ID3_FIELDS
        for key, value in changes.items():
            name = names[key]
            tags.delall(name)
            for frame in tags.getall('TXXX'):
                if frame.desc.casefold() in ID3_TEXT_ALIASES.get(key, (key,)):
                    del tags[frame.HashKey]
            if key == 'date':
                tags.delall('TYER')
            if not value:
                continue
            if key == 'lyrics':
                tags.add(USLT(encoding=3, lang='eng', desc='', text=value))
            elif key == 'comment':
                tags.add(COMM(encoding=3, lang='eng', desc='', text=[value]))
            else:
                tags.add(Frames[name](encoding=3, text=[value]))
    elif isinstance(tags, MP4Tags):
        names = MP4_FIELDS
        for key, value in changes.items():
            name = names[key]
            tags.pop(name, None)
            if value:
                if key in ('track', 'disc'):
                    parts = value.split('/')
                    if len(parts) > 2 or not all(part.isdecimal() for part in parts):
                        raise MusicError(
                            'Track and disc values must be numbers, optionally followed by /total.'
                        )
                    tags[name] = [
                        (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
                    ]
                else:
                    tags[name] = [value]
    else:
        aliases = {
            'album_artist': ('album_artist', 'albumartist'),
            'date': ('date', 'year'),
            'track': ('track', 'tracknumber', 'tracktotal', 'totaltracks'),
            'disc': ('disc', 'discnumber', 'disctotal', 'totaldiscs'),
            'comment': ('comment', 'description'),
            'lyrics': ('lyrics', 'unsyncedlyrics'),
        }
        names = {
            'album_artist': 'albumartist',
            'track': 'tracknumber',
            'disc': 'discnumber',
        }
        for key, value in changes.items():
            for alias in aliases.get(key, (key,)):
                if alias in tags:
                    del tags[alias]
            if value:
                tags[names.get(key, key)] = [value]
    audio.save()


def replace_cover(path, data, mime):
    """Replace only the attached front cover; every other tag stays untouched."""
    audio = File(path)
    if audio is None:
        raise MusicError('This file has no supported tag container.')
    if audio.tags is None:
        audio.add_tags()
    if isinstance(audio, FLAC):
        picture = Picture()
        picture.type = PictureType.COVER_FRONT
        picture.mime = mime
        picture.desc = 'Cover'
        picture.data = data
        audio.clear_pictures()
        audio.add_picture(picture)
    elif isinstance(audio.tags, ID3):
        audio.tags.delall('APIC')
        audio.tags.add(
            APIC(
                encoding=3,
                mime=mime,
                type=PictureType.COVER_FRONT,
                desc='Cover',
                data=data,
            )
        )
    elif isinstance(audio.tags, MP4Tags):
        image_format = (
            MP4Cover.FORMAT_PNG if mime == 'image/png' else MP4Cover.FORMAT_JPEG
        )
        audio.tags['covr'] = [MP4Cover(data, imageformat=image_format)]
    else:
        raise MusicError('Cover editing supports MP3, FLAC and M4A files.')
    audio.save()


def format_summary(extension, *, bits=0, rate=0, channels=0, bitrate=0):
    summary = [extension.upper()]
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
    return ' · '.join(filter(None, summary))


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
    if Path(path).suffix.lower() in TAG_FORMATS:
        try:
            if audio_file := File(path):
                tags.update(fields(audio_file))
        except MutagenError:
            pass
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
        fileInfo=format_summary(
            Path(path).suffix.lstrip('.') or stream.get('codec_name', ''),
            bits=bits,
            rate=rate,
            channels=channels,
            bitrate=bitrate,
        ),
        coverIndexes=covers,
    )


def cover_data(image, codec, run, register, unregister):
    """JPEG and PNG embed unchanged; other images become a high-quality JPEG."""
    if codec in ('mjpeg', 'png'):
        # Embedded bytes are never decoded here, so prove they decode first.
        decode = ['ffmpeg', '-v', 'error', '-nostdin', '-i', str(image)]
        if run(decode + ['-frames:v', '1', '-f', 'null', '-'], 20)[0]:
            raise MusicError('The selected file could not be read as an image.')
        return image.read_bytes(), 'image/png' if codec == 'png' else 'image/jpeg'
    fd, name = tempfile.mkstemp(prefix='.music-cover-', suffix='.jpg')
    os.close(fd)
    converted = Path(name)
    register(converted)
    try:
        code, _ = run(
            ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(image)]
            + ['-frames:v', '1', '-c:v', 'mjpeg', '-q:v', '2', str(converted)],
            20,
        )
        if code or not converted.stat().st_size:
            raise MusicError('The selected file could not be read as an image.')
        return converted.read_bytes(), 'image/jpeg'
    finally:
        converted.unlink(missing_ok=True)
        unregister(converted)


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

        if path.suffix.lower() not in COVER_FORMATS:
            raise MusicError('Cover editing supports MP3, FLAC and M4A files.')
        parsed = urlsplit(str(artwork))
        if parsed.scheme not in ('', 'file') or parsed.netloc not in ('', 'localhost'):
            raise MusicError('Choose a local image file.')
        try:
            image = Path(
                unquote(parsed.path) if parsed.scheme else str(artwork)
            ).resolve(strict=True)
        except OSError:
            raise MusicError('The selected image is no longer available.') from None
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
                'stream=codec_name,width,height',
                '-of',
                'json',
                str(image),
            ],
            20,
        )
        streams = json.loads(output).get('streams') if not code else None
        stream = streams[0] if streams else {}
        codec = stream.get('codec_name')
        # The picker offers these; FFmpeg would also "decode" text as ANSI art.
        if codec not in ('mjpeg', 'png', 'webp') or not (
            stream.get('width') and stream.get('height')
        ):
            raise MusicError('The selected file could not be read as an image.')
        image_signature = signature(image)
    before = signature(path)
    original = read(path, run)['tags']
    fd, name = tempfile.mkstemp(
        prefix='.music-tags-', suffix=path.suffix, dir=path.parent
    )
    os.close(fd)
    temporary = Path(name)
    register(temporary)
    try:
        if path.suffix.lower() in TAG_FORMATS:
            # Mutagen edits a private copy in place: custom frames, ratings,
            # lyrics and audio packets survive, unlike an FFmpeg remux.
            shutil.copyfile(path, temporary)
            try:
                if changes:
                    update_tags(temporary, changes)
                if image:
                    replace_cover(
                        temporary, *cover_data(image, codec, run, register, unregister)
                    )
            except MutagenError:
                raise MusicError(
                    'The tags could not be saved. The original song was kept.'
                ) from None
        else:
            command = ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(path)]
            command += ['-map', '0', '-map_metadata', '0', '-map_chapters', '0']
            command += ['-c', 'copy']
            for key, value in changes.items():
                command += ['-metadata', key + '=' + value]
                if path.suffix.lower() in ('.mka', '.mkv'):
                    command += ['-metadata:s:a:0', key + '=' + value]
            if run(command + [str(temporary)])[0]:
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
        expected = original | changes
        if any(actual.get(key, '') != value for key, value in expected.items()):
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
