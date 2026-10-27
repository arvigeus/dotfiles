"""Validated FFmpeg video presets and atomic, non-overwriting output publication."""

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


def read_presets(path):
    data = json.loads(Path(path).read_text())
    if (
        not isinstance(data, dict)
        or data.get('version') != 1
        or not isinstance(data.get('presets'), list)
        or not data['presets']
    ):
        raise ValueError('Expected version 1 and a non-empty presets list.')
    seen = set()
    keys = {
        'id',
        'name',
        'description',
        'extension',
        'mode',
        'codec',
        'quality',
        'speed',
        'max_width',
        'max_height',
        'audio_codec',
        'audio_bitrate',
        'pixel_format',
    }
    for preset in data['presets']:
        if not isinstance(preset, dict) or set(preset) - keys:
            raise ValueError('Unknown preset fields.')
        for key in ('id', 'name', 'extension', 'mode'):
            if not isinstance(preset.get(key), str) or not preset[key]:
                raise ValueError('Missing ' + key)
        if not re.fullmatch('[a-z0-9-]+', preset['id']) or preset['id'] in seen:
            raise ValueError('Invalid or duplicate preset ID.')
        seen.add(preset['id'])
        if preset['extension'] not in ('mp4', 'mkv', 'webm', 'm4a'):
            raise ValueError('Unsupported output container.')
        if preset['mode'] not in ('copy', 'encode', 'audio'):
            raise ValueError('Unknown conversion mode.')
        if not isinstance(preset.get('description', ''), str):
            raise TypeError('Descriptions must be text.')
        for key in ('codec', 'audio_codec'):
            if key in preset and (
                not isinstance(preset[key], str)
                or not re.fullmatch('[a-zA-Z0-9_-]+', preset[key])
            ):
                raise ValueError('Invalid ' + key)
        if preset['mode'] == 'encode' and preset.get('codec') not in (
            'libx264',
            'libx265',
            'libvpx-vp9',
            'libsvtav1',
        ):
            raise ValueError('Unsupported video encoder.')
        if preset.get('codec') == 'libsvtav1':
            if 'speed' in preset and (
                type(preset['speed']) is not int or not 0 <= preset['speed'] <= 13
            ):
                raise ValueError('SVT-AV1 speed must be an integer from 0 to 13.')
        elif 'speed' in preset and (
            not isinstance(preset['speed'], str)
            or not re.fullmatch('[a-zA-Z0-9_-]+', preset['speed'])
        ):
            raise ValueError('Invalid encoder speed.')
        if 'pixel_format' in preset and preset['pixel_format'] not in (
            'yuv420p',
            'yuv420p10le',
        ):
            raise ValueError('Unsupported pixel format.')
        maximum_quality = (
            63 if preset.get('codec') in ('libsvtav1', 'libvpx-vp9') else 51
        )
        for key, low, high in [
            ('quality', 0, maximum_quality),
            ('max_width', 2, 16384),
            ('max_height', 2, 16384),
        ]:
            if key in preset and (
                type(preset[key]) is not int or not low <= preset[key] <= high
            ):
                raise ValueError('Invalid ' + key)
        if ('max_width' in preset) != ('max_height' in preset):
            raise ValueError('Set both maximum dimensions.')
        if 'audio_bitrate' in preset and not re.fullmatch(
            '[1-9][0-9]*k', str(preset['audio_bitrate'])
        ):
            raise ValueError('Invalid audio bitrate.')
    return data['presets']


def probe_command(path):
    return [
        'ffprobe',
        '-v',
        'error',
        '-show_format',
        '-show_streams',
        '-show_chapters',
        '-of',
        'json',
        str(path),
    ]


def video_info(document):
    info = json.loads(document)
    if not any(
        s.get('codec_type') == 'video'
        and not s.get('disposition', {}).get('attached_pic')
        for s in info.get('streams', [])
    ):
        raise ValueError('This file contains no video stream.')
    return info


@dataclass
class Operation:
    command: list
    temporary: Path
    target: Path

    def abort(self):
        self.temporary.unlink(missing_ok=True)

    def finish(self):
        try:
            os.link(self.temporary, self.target)
        finally:
            self.abort()


def conversion(source, preset, folder=None):
    source = Path(source).resolve(strict=True)
    target = (
        Path(folder) if folder else source.parent
    ) / f'{source.stem} [{preset["id"]}].{preset["extension"]}'
    if target.exists() or target.is_symlink():
        raise FileExistsError('Output already exists: ' + target.name)
    fd, name = tempfile.mkstemp(
        prefix='.video-tools-', suffix=target.suffix, dir=target.parent
    )
    os.close(fd)
    command = ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(source)]
    mode = preset['mode']
    if mode == 'copy':
        command += ['-map', '0', '-c', 'copy']
    elif mode == 'audio':
        command += [
            '-map',
            '0:a:0',
            '-vn',
            '-c:a',
            preset.get('audio_codec', 'aac'),
            '-b:a',
            preset.get('audio_bitrate', '192k'),
        ]
    else:
        default_pixel_format = (
            'yuv420p10le' if preset['codec'] == 'libsvtav1' else 'yuv420p'
        )
        command += [
            '-map',
            '0:V:0',
            '-map',
            '0:a?',
            '-c:v',
            preset['codec'],
            '-crf',
            str(preset.get('quality', 32 if preset['codec'] == 'libsvtav1' else 23)),
            '-pix_fmt',
            preset.get('pixel_format', default_pixel_format),
        ]
        if preset['codec'] == 'libvpx-vp9':
            command += ['-b:v', '0', '-row-mt', '1', '-cpu-used', '4']
        elif preset['codec'] == 'libsvtav1':
            command += ['-preset', str(preset.get('speed', 6))]
        else:
            command += ['-preset', preset.get('speed', 'medium')]
        width, height = preset.get('max_width', 16384), preset.get('max_height', 16384)
        command += [
            '-vf',
            f'scale=w=min({width}\\,iw):h=min({height}\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2',
        ]
        command += [
            '-c:a',
            preset.get('audio_codec', 'aac'),
            '-b:a',
            preset.get('audio_bitrate', '192k'),
        ]
    command += ['-map_metadata', '0', '-map_chapters', '0']
    if preset['extension'] in ('mp4', 'm4a'):
        command += ['-movflags', '+faststart']
    command += ['-progress', 'pipe:1', '-nostats', name]
    return Operation(command, Path(name), target)
