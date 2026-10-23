"""Audio probing, validated presets and atomic FFmpeg operations."""
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

FIELDS = {'title': 'Title', 'artist': 'Artist', 'album': 'Album', 'album_artist': 'Album artist',
          'date': 'Date', 'track': 'Track / total', 'disc': 'Disc / total', 'genre': 'Genre',
          'composer': 'Composer', 'comment': 'Comment', 'lyrics': 'Lyrics'}
ART_FORMATS = {'.mp3', '.flac', '.m4a', '.mp4'}


def read_presets(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('presets'), list) or not data['presets']:
        raise ValueError('Expected version 1 and a non-empty presets list.')
    seen = set()
    allowed = {'id', 'name', 'description', 'extension', 'codec', 'bitrate', 'quality',
               'compression', 'sample_rate', 'channels'}
    for p in data['presets']:
        if not isinstance(p, dict) or set(p) - allowed:
            raise ValueError('Unknown preset fields.')
        if not isinstance(p.get('id'), str) or not re.fullmatch(r'[a-z0-9-]+', p['id']) or p['id'] in seen:
            raise ValueError('Preset IDs must be unique lowercase names with optional hyphens.')
        seen.add(p['id'])
        for key in ('name', 'extension', 'codec'):
            if not isinstance(p.get(key), str) or not p[key]:
                raise ValueError(f'Missing preset {key}.')
        if 'description' in p and not isinstance(p['description'], str):
            raise ValueError('Preset descriptions must be text.')
        if not re.fullmatch(r'[a-z0-9]+', p['extension']) or not re.fullmatch(r'[a-zA-Z0-9_]+', p['codec']):
            raise ValueError('Invalid codec or file extension.')
        if 'bitrate' in p and not re.fullmatch(r'[1-9][0-9]*k?', str(p['bitrate'])):
            raise ValueError('Bitrate must be a positive number, optionally followed by k.')
        for key, low, high in [('quality', -1, 10), ('compression', 0, 12),
                               ('sample_rate', 8000, 384000), ('channels', 1, 8)]:
            if key in p and (type(p[key]) is not int or not low <= p[key] <= high):
                raise ValueError(f'Invalid {key}. Expected an integer from {low} to {high}.')
    return data['presets']


def probe_command(path):
    return ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]


def audio_info(document):
    data = json.loads(document)
    audio = [s for s in data.get('streams', []) if s.get('codec_type') == 'audio']
    if not audio:
        raise ValueError('This file contains no audio stream.')
    tags = {k.lower(): str(v) for s in audio[:1] for k, v in s.get('tags', {}).items()}
    tags.update({k.lower(): str(v) for k, v in data.get('format', {}).get('tags', {}).items()})
    tags['album_artist'] = tags.get('album_artist', tags.get('albumartist', ''))
    tags['date'] = tags.get('date', tags.get('year', ''))
    return {'tags': tags, 'audio': audio, 'format': data.get('format', {}),
            'artwork': sum(bool(s.get('disposition', {}).get('attached_pic')) for s in data.get('streams', []))}


def signature(path):
    s = path.stat()
    return s.st_ino, s.st_size, s.st_mtime_ns


@dataclass
class Operation:
    command: list
    temporary: Path
    target: Path
    original: tuple | None = None
    backup: bool = False
    expected_tags: dict | None = None
    expected_artwork: bool | None = None

    def abort(self):
        self.temporary.unlink(missing_ok=True)

    def finish(self):
        try:
            if self.original is not None:
                info = audio_info(subprocess.check_output(probe_command(self.temporary), timeout=15))
                for key, value in (self.expected_tags or {}).items():
                    if info['tags'].get(key, '') != value:
                        raise ValueError(f'This container could not preserve the {FIELDS[key]} edit. Source was kept.')
                if self.expected_artwork is not None and bool(info['artwork']) != self.expected_artwork:
                    raise ValueError('This container could not preserve the cover edit. Source was kept.')
                if signature(self.target) != self.original:
                    raise ValueError('The source changed during editing. Reload it before saving.')
                os.chmod(self.temporary, stat.S_IMODE(self.target.stat().st_mode))
                if self.backup:
                    candidate = Path(str(self.target) + '.tags-backup')
                    index = 1
                    while True:
                        try:
                            os.link(self.target, candidate)
                            break
                        except FileExistsError:
                            index += 1
                            candidate = Path(str(self.target) + f'.tags-backup-{index}')
                os.replace(self.temporary, self.target)
            else:
                # Publish atomically, without overwriting a path created meanwhile.
                os.link(self.temporary, self.target)
        finally:
            self.abort()


def temporary_for(target):
    fd, name = tempfile.mkstemp(prefix='.audio-tools-', suffix=target.suffix, dir=target.parent)
    os.close(fd)
    return Path(name)


def base_command(source):
    return ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(source)]


def conversion(source, preset, folder=None, normalize=False):
    source = Path(source).resolve(strict=True)
    target = (Path(folder) if folder else source.parent) / f'{source.stem} [{preset["id"]}].{preset["extension"]}'
    if target.exists() or target.is_symlink():
        raise FileExistsError(f'Output already exists: {target.name}')
    temporary = temporary_for(target)
    command = base_command(source) + ['-map', '0:a:0', '-map_metadata', '0', '-map_chapters', '0', '-c:a', preset['codec']]
    for key, flag in [('bitrate', '-b:a'), ('quality', '-q:a'), ('compression', '-compression_level'),
                      ('sample_rate', '-ar'), ('channels', '-ac')]:
        if key in preset:
            command += [flag, str(preset[key])]
    # Preserve artwork in containers that support attached pictures.
    if target.suffix in ART_FORMATS:
        command += ['-map', '0:v?', '-c:v', 'mjpeg', '-disposition:v', 'attached_pic']
    if normalize:
        command += ['-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-ar', str(preset.get('sample_rate', 48000))]
    command += ['-progress', 'pipe:1', '-nostats', str(temporary)]
    return Operation(command, temporary, target)


def tag_edit(source, changes, artwork=None, backup=True):
    source = Path(source).resolve(strict=True)
    if source.stat().st_nlink > 1:
        raise ValueError('Tag editing a hard-linked file is disabled. Make a separate copy first.')
    if set(changes) - FIELDS.keys():
        raise ValueError('Unknown tag fields.')
    if artwork is not None and source.suffix.lower() not in ART_FORMATS:
        raise ValueError('Cover editing supports MP3, FLAC and M4A files.')
    if artwork:
        artwork = str(Path(artwork).resolve(strict=True))
    original = signature(source)
    temporary = temporary_for(source)
    command = base_command(source)
    if artwork:
        command += ['-i', artwork]
    command += ['-map', '0', '-map_metadata', '0', '-map_chapters', '0', '-c', 'copy']
    if artwork is not None:
        command += ['-map', '-0:v?']
        if artwork:
            command += ['-map', '1:v:0', '-c:v', 'mjpeg', '-disposition:v', 'attached_pic',
                        '-metadata:s:v', 'title=Cover', '-metadata:s:v', 'comment=Cover (front)']
    for key, value in changes.items():
        command += ['-metadata', f'{key}={value}']
        if source.suffix.lower() in ('.mka', '.mkv'):
            command += ['-metadata:s:a:0', f'{key}={value}']
    command += ['-progress', 'pipe:1', '-nostats', str(temporary)]
    return Operation(command, temporary, source, original, backup, changes,
                     None if artwork is None else bool(artwork))
