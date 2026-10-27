#!/usr/bin/env python3
"""Local video subtitle inventory, OpenSubtitles search, and sidecar management."""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spaces.movies.local import (
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    episode_numbers,
    library_root,
)

from spaces.movies.paths import CONFIG_DIR, DATA, SPACE

CONFIG = CONFIG_DIR / 'media.json'

API = 'https://api.opensubtitles.com/api/v1'
LANGUAGE_ALIASES = {
    'bul': 'bg',
    'vie': 'vi',
    'eng': 'en',
    'fra': 'fr',
    'fre': 'fr',
    'deu': 'de',
    'ger': 'de',
    'spa': 'es',
    'ita': 'it',
    'por': 'pt',
    'rus': 'ru',
    'jpn': 'ja',
    'kor': 'ko',
    'zho': 'zh',
    'chi': 'zh',
}
STAMP = re.compile(r'(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})')
CUE = re.compile(r'(?m)^\s*' + STAMP.pattern + r'\s*-->\s*' + STAMP.pattern)


class SubtitleError(Exception):
    pass


def language(code):
    code = str(code or '').strip().lower().replace('_', '-')
    return LANGUAGE_ALIASES.get(code, code)


def fps(value):
    try:
        result = float(Fraction(str(value)))
        return round(result, 5) if 10 <= result <= 120 else 0
    except (ValueError, ZeroDivisionError):
        return 0


def moviehash(path):
    size = path.stat().st_size
    if size < 131072:
        return ''
    with path.open('rb') as stream:
        start = stream.read(65536)
        stream.seek(size - 65536)
        end = stream.read(65536)
    values = (
        int.from_bytes(block[i : i + 8], 'little')
        for block in (start, end)
        for i in range(0, 65536, 8)
    )
    return f'{(size + sum(values)) & 0xFFFFFFFFFFFFFFFF:016x}'


def retime_srt(content, source_fps, target_fps, offset=0):
    source, target = fps(source_fps), fps(target_fps)
    if not source or not target or not -600 <= float(offset) <= 600:
        raise SubtitleError(
            'Enter frame rates from 10 to 120 and an offset within 10 minutes.'
        )
    if not CUE.search(content):
        raise SubtitleError('Only SRT subtitles with timestamp cues can be adjusted.')
    factor = source / target

    def convert(match):
        hours, minutes, seconds, millis = map(int, match.groups())
        value = max(
            0,
            round(
                (hours * 3600000 + minutes * 60000 + seconds * 1000 + millis) * factor
                + float(offset) * 1000
            ),
        )
        hours, value = divmod(value, 3600000)
        minutes, value = divmod(value, 60000)
        seconds, millis = divmod(value, 1000)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}'

    return CUE.sub(lambda cue: STAMP.sub(convert, cue.group(0)), content)


def decode_subtitle(payload):
    if len(payload) > 3 * 1024 * 1024:
        raise SubtitleError('The subtitle file is too large.')
    for encoding in ('utf-8-sig', 'utf-16'):
        try:
            text = payload.decode(encoding)
            if CUE.search(text):
                return text
        except UnicodeError:
            pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(payload).best()
        if best and CUE.search(str(best)):
            return str(best)
    except ImportError:
        pass
    raise SubtitleError('The downloaded subtitle is not a readable SRT file.')


def release_info(path, kind):
    choices = [path.with_suffix('.release.nfo')]
    if kind == 'movie':
        choices.append(path.parent / 'movie.nfo')
    node = None
    for nfo in choices:
        try:
            root = ET.parse(nfo).getroot()
            node = next(
                (item for item in root if item.tag.lower().endswith('release')), None
            )
        except (OSError, ET.ParseError):
            continue
        if node is not None:
            break
    if node is None:
        return {'name': path.stem, 'originalFilename': path.name, 'source': ''}
    return {
        'name': node.findtext('name') or path.stem,
        'originalFilename': node.findtext('originalfilename') or path.name,
        'source': node.findtext('source') or '',
    }


def sidecar_language(path):
    parts = re.split(r'[. _-]+', path.stem)
    for part in reversed(parts):
        code = part.lower()
        if code in ('sdh', 'hi', 'cc', 'forced', 'retimed', 'embedded'):
            continue
        if re.fullmatch(r'[a-z]{2}', code) or code in LANGUAGE_ALIASES:
            return language(code)
    return 'und'


class OpenSubtitles:
    def __init__(self, settings):
        self.key = str(settings.get('api_key') or '')
        self.username = str(settings.get('username') or '')
        self.password = str(settings.get('password') or '')
        self.token = ''
        self.base = API

    def request(self, path, params=None, *, body=None, authorized=False, retry=True):
        if not self.key:
            raise SubtitleError(
                'Add an OpenSubtitles API key to media.json to search subtitles.'
            )
        if authorized and not self.token:
            self.login()
        url = self.base + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        headers = {
            'Api-Key': self.key,
            'User-Agent': 'MoviesSpace/1.0',
            'Accept': 'application/json',
        }
        if authorized:
            headers['Authorization'] = 'Bearer ' + self.token
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise SubtitleError('OpenSubtitles returned too much data.')
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            if code == 401 and authorized and retry:
                self.token = ''
                self.base = API
                self.login()
                return self.request(
                    path, params, body=body, authorized=True, retry=False
                )
            if code == 401:
                raise SubtitleError(
                    'OpenSubtitles rejected the account or API key.'
                ) from None
            if code == 403:
                raise SubtitleError(
                    'OpenSubtitles rejected the API key or account access.'
                ) from None
            if code == 406:
                raise SubtitleError(
                    'OpenSubtitles download quota reached. Try again after it resets.'
                ) from None
            if code == 429:
                raise SubtitleError(
                    'OpenSubtitles rate or download limit reached. Try again later.'
                ) from None
            raise SubtitleError(f'OpenSubtitles returned HTTP {code}.') from None
        except (OSError, UnicodeError, ValueError):
            raise SubtitleError(
                'OpenSubtitles is unavailable or returned an invalid response.'
            ) from None

    def login(self):
        if not self.username or not self.password:
            raise SubtitleError(
                'Add your OpenSubtitles username and password to media.json to download.'
            )
        result = self.request(
            '/login', body={'username': self.username, 'password': self.password}
        )
        host = result.get('base_url')
        if host not in (
            'api.opensubtitles.com',
            'vip-api.opensubtitles.com',
        ) or not result.get('token'):
            raise SubtitleError('OpenSubtitles did not return a usable login token.')
        self.base = 'https://' + host + '/api/v1'
        self.token = result['token']

    def download(self, file_id):
        result = self.request(
            '/download', body={'file_id': file_id, 'sub_format': 'srt'}, authorized=True
        )
        link = str(result.get('link') or '')
        host = urllib.parse.urlsplit(link).hostname or ''
        if not link.startswith('https://') or not (
            host == 'opensubtitles.com' or host.endswith('.opensubtitles.com')
        ):
            raise SubtitleError('OpenSubtitles returned an unexpected download link.')
        try:
            with urllib.request.urlopen(
                urllib.request.Request(link, headers={'User-Agent': 'MoviesSpace/1.0'}),
                timeout=30,
            ) as response:
                final = urllib.parse.urlsplit(response.geturl())
                if final.scheme != 'https' or not (
                    final.hostname == 'opensubtitles.com'
                    or (final.hostname or '').endswith('.opensubtitles.com')
                ):
                    raise SubtitleError(
                        'OpenSubtitles redirected to an unexpected download host.'
                    )
                payload = response.read(3 * 1024 * 1024 + 1)
            return payload, result.get('remaining')
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise SubtitleError(f'Subtitle download returned HTTP {code}.') from None
        except OSError:
            raise SubtitleError('Could not download the subtitle file.') from None


class SubtitleBackend:
    def __init__(self, config=CONFIG, data=DATA, client=None):
        self.config_path = Path(config)
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.client_override = client
        self.client = None
        self.selections = {}
        self.selection_lock = threading.RLock()
        with self.db() as db:
            db.execute(
                'CREATE TABLE IF NOT EXISTS subtitle_managed ('
                'path TEXT PRIMARY KEY, video_path TEXT NOT NULL)'
            )

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.data / 'library.sqlite', timeout=20)
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self):
        content = self.config()
        config = content.get('opensubtitles') or {}
        if not isinstance(config, dict):
            raise SubtitleError('opensubtitles in media.json must be an object.')
        return config

    def config(self):
        try:
            content = json.loads(self.config_path.read_text())
        except FileNotFoundError:
            content = {}
        except (OSError, ValueError):
            raise SubtitleError('Cannot read media.json.') from None
        if not isinstance(content, dict):
            raise SubtitleError('media.json must contain an object.')
        return content

    def opensubtitles(self):
        if self.client_override:
            return self.client_override
        if self.client is None:
            self.client = OpenSubtitles(self.settings())
        return self.client

    def registered(self, path):
        path = Path(str(path or '')).expanduser()
        with self.db() as db:
            row = db.execute(
                'SELECT kind,title_json,season,episode,path FROM local_files WHERE path=?',
                (str(path),),
            ).fetchone()
        if (
            not row
            or row[0] not in ('movie', 'tv')
            or not path.is_file()
            or path.is_symlink()
        ):
            raise SubtitleError('Choose a registered Local movie or episode.')
        if not path.resolve().is_relative_to(library_root(row[0]).resolve()):
            raise SubtitleError('The video is outside its Local library.')
        return path, {
            'kind': row[0],
            'title': json.loads(row[1]),
            'season': row[2],
            'episode': row[3],
        }

    def probe(self, path):
        try:
            run = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            streams = json.loads(run.stdout).get('streams', [])
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0, []
        video = next(
            (stream for stream in streams if stream.get('codec_type') == 'video'), {}
        )
        rate = fps(video.get('avg_frame_rate')) or fps(video.get('r_frame_rate'))
        embedded = []
        for stream in streams:
            if stream.get('codec_type') != 'subtitle':
                continue
            tags = {key.lower(): value for key, value in stream.get('tags', {}).items()}
            codec = str(stream.get('codec_name') or '')
            embedded.append(
                {
                    'index': stream.get('index'),
                    'language': language(tags.get('language')) or 'und',
                    'title': tags.get('title') or '',
                    'codec': codec,
                    'forced': bool(stream.get('disposition', {}).get('forced')),
                    'extractable': codec
                    in ('subrip', 'ass', 'ssa', 'mov_text', 'webvtt'),
                }
            )
        return rate, embedded

    def sidecars(self, video):
        output = []
        with self.db() as db:
            managed = {
                row[0]
                for row in db.execute(
                    'SELECT path FROM subtitle_managed WHERE video_path=?',
                    (str(video),),
                )
            }
        number = episode_numbers(video.name)
        original = Path(
            release_info(video, 'tv' if number else 'movie')['originalFilename']
        ).stem
        one_video = (
            sum(
                path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
                for path in video.parent.iterdir()
            )
            == 1
        )
        for path in sorted(video.parent.iterdir()):
            subtitle_number = episode_numbers(path.name)
            related = (
                path.name.startswith(video.stem + '.')
                or path.name.startswith(original + '.')
                or (subtitle_number == number if subtitle_number else one_video)
            )
            if (
                path.is_file()
                and not path.is_symlink()
                and path.suffix.lower() in SUBTITLE_EXTENSIONS
                and related
            ):
                output.append(
                    {
                        'path': str(path),
                        'name': path.name,
                        'language': sidecar_language(path),
                        'format': path.suffix.lower().lstrip('.'),
                        'size': path.stat().st_size,
                        'managed': str(path) in managed,
                    }
                )
        return output

    def languages(self):
        languages = self.settings().get('languages', ['en'])
        if not isinstance(languages, list):
            return ['en']
        return [
            language(value)
            for value in languages
            if re.fullmatch(r'[a-zA-Z]{2,3}', str(value))
        ][:5]

    def inspect(self, request):
        path, record = self.registered(request.get('path'))
        rate, embedded = self.probe(path)
        return {
            'path': str(path),
            'name': path.name,
            'fps': rate,
            'embedded': embedded,
            'files': self.sidecars(path),
            'release': release_info(path, record['kind']),
            'configured': bool(self.settings().get('api_key')),
            'languages': self.languages(),
        }

    def search(self, request):
        path, record = self.registered(request.get('path'))
        try:
            page = int(request.get('page') or 1)
        except (ValueError, TypeError):
            raise SubtitleError('Invalid subtitle results page.') from None
        if not 1 <= page <= 20:
            raise SubtitleError('Invalid subtitle results page.')
        requested = request.get('languages') or self.languages()
        if not isinstance(requested, list):
            raise SubtitleError('Choose subtitle languages from the list.')
        languages = list(dict.fromkeys(language(value) for value in requested))
        if (
            not languages
            or len(languages) > 5
            or any(not re.fullmatch(r'[a-z]{2,3}', value) for value in languages)
        ):
            raise SubtitleError('Choose one to five subtitle languages.')
        title = record['title']
        identity = {}
        imdb = re.fullmatch(
            r'tt(\d+)', str(title.get('imdbId') or title.get('id') or '')
        )
        tmdb_alias = re.fullmatch(
            r'tmdb:(?:movie|tv):(\d+)', str(title.get('id') or '')
        )
        tmdb = title.get('tmdbId') or (tmdb_alias[1] if tmdb_alias else None)
        if record['kind'] == 'tv':
            identity.update(
                season_number=record['season'], episode_number=record['episode']
            )
            if imdb:
                identity['parent_imdb_id'] = imdb[1]
            elif tmdb:
                identity['parent_tmdb_id'] = tmdb
        elif imdb:
            identity['imdb_id'] = imdb[1]
        elif tmdb:
            identity['tmdb_id'] = tmdb
        else:
            identity['query'] = title.get('title') or path.stem
            if title.get('year'):
                identity['year'] = str(title['year'])[:4]
        fingerprint = moviehash(path)
        release = release_info(path, record['kind'])
        expected = set(
            re.findall(
                r'[a-z0-9]{3,}',
                (release['name'] + ' ' + release['originalFilename']).lower(),
            )
        )
        client = self.opensubtitles()
        found = {}
        searches = (
            [({'moviehash': fingerprint, 'languages': ','.join(languages)}, True)]
            if fingerprint and page == 1
            else []
        )
        searches += [
            (identity | {'languages': code, 'page': page}, False) for code in languages
        ]
        more = False
        for params, exact in searches:
            response = client.request('/subtitles', params=params)
            if not isinstance(response.get('data'), list):
                raise SubtitleError('OpenSubtitles returned invalid search results.')
            if not exact:
                more |= int(response.get('total_pages') or 1) > page
            for item in response.get('data', [])[:50]:
                attrs = item.get('attributes') or {}
                code = language(attrs.get('language'))
                feature = attrs.get('feature_details') or {}
                if code not in languages or (
                    record['kind'] == 'tv'
                    and (
                        int(feature.get('season_number') or 0) != record['season']
                        or int(feature.get('episode_number') or 0) != record['episode']
                    )
                ):
                    continue
                words = set(
                    re.findall(r'[a-z0-9]{3,}', str(attrs.get('release') or '').lower())
                )
                overlap = len(expected & words)
                for file in attrs.get('files') or []:
                    file_id = file.get('file_id')
                    if not isinstance(file_id, int):
                        continue
                    row = {
                        'fileId': file_id,
                        'language': code,
                        'release': attrs.get('release') or file.get('file_name') or '',
                        'fileName': file.get('file_name') or '',
                        'fps': fps(attrs.get('fps')),
                        'downloads': int(attrs.get('download_count') or 0),
                        'trusted': bool(attrs.get('from_trusted')),
                        'hearingImpaired': bool(attrs.get('hearing_impaired')),
                        'forced': bool(attrs.get('foreign_parts_only')),
                        'hashMatch': exact,
                        'releaseMatch': overlap,
                        'disc': int(file.get('cd_number') or 1),
                    }
                    previous = found.get(file_id)
                    if previous:
                        row['hashMatch'] |= previous['hashMatch']
                    found[file_id] = row
        order = {code: index for index, code in enumerate(languages)}
        items = sorted(
            found.values(),
            key=lambda row: (
                order[row['language']],
                -int(row['hashMatch']),
                -int(row['releaseMatch']),
                -int(row['trusted']),
                -int(row['downloads']),
            ),
        )
        with self.selection_lock:
            if page == 1:
                search_id = uuid.uuid4().hex
                self.selections[search_id] = {
                    'path': str(path),
                    'languages': languages,
                    'files': {},
                }
                while len(self.selections) > 10:
                    self.selections.pop(next(iter(self.selections)))
            else:
                search_id = str(request.get('searchId') or '')
                selection = self.selections.get(search_id)
                if (
                    not selection
                    or selection['path'] != str(path)
                    or selection['languages'] != languages
                ):
                    raise SubtitleError('Search again before loading more subtitles.')
                items = [
                    row for row in items if row['fileId'] not in selection['files']
                ]
            self.selections[search_id]['files'].update(
                {row['fileId']: row for row in items}
            )
        return {
            'items': items,
            'searchId': search_id,
            'languages': languages,
            'nextPage': page + 1 if more else 0,
        }

    def target(self, video, code, marker=''):
        if not re.fullmatch(r'[a-z]{2,3}', code):
            raise SubtitleError('Invalid subtitle language.')
        index = 1
        while True:
            parts = [video.stem]
            if marker:
                parts.append(marker if index == 1 else marker + str(index))
            elif index > 1:
                parts.append(str(index))
            parts.append(code)
            candidate = video.with_name('.'.join(parts) + '.srt')
            if not candidate.exists():
                return candidate
            index += 1

    def save(self, target, content, video):
        if not CUE.search(content):
            raise SubtitleError('The subtitle file has no SRT cues.')
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=target.parent,
            prefix='.' + SPACE + '-sub-',
            delete=False,
        ) as stream:
            temp = Path(stream.name)
            stream.write(content.replace('\r\n', '\n'))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp, target)
        except FileExistsError:
            raise SubtitleError(
                'A subtitle with that name was added. Refresh and try again.'
            ) from None
        finally:
            temp.unlink(missing_ok=True)
        try:
            with self.db() as db:
                db.execute(
                    'INSERT INTO subtitle_managed(path,video_path) VALUES (?,?)',
                    (str(target), str(video)),
                )
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return str(target)

    def download(self, request):
        video, _ = self.registered(request.get('path'))
        try:
            file_id = int(request.get('fileId'))
        except (ValueError, TypeError):
            raise SubtitleError('Choose a subtitle search result.') from None
        with self.selection_lock:
            selection = self.selections.get(str(request.get('searchId') or '')) or {}
            row = (
                selection.get('files', {}).get(file_id)
                if selection.get('path') == str(video)
                else None
            )
        if not row:
            raise SubtitleError('Search again before downloading this subtitle.')
        payload, remaining = self.opensubtitles().download(file_id)
        content = decode_subtitle(payload)
        video_fps = self.probe(video)[0]
        adapted = False
        if (
            request.get('adapt')
            and row['fps']
            and video_fps
            and abs(row['fps'] - video_fps) > 0.01
        ):
            content = retime_srt(content, row['fps'], video_fps)
            adapted = True
        target = self.target(video, row['language'], 'forced' if row['forced'] else '')
        return {
            'path': self.save(target, content, video),
            'remaining': remaining,
            'adapted': adapted,
        }

    def sidecar(self, video, value):
        path = Path(str(value or ''))
        if str(path) not in {item['path'] for item in self.sidecars(video)}:
            raise SubtitleError('Choose a subtitle beside this video.')
        return path

    def retime(self, request):
        video, _ = self.registered(request.get('path'))
        source = self.sidecar(video, request.get('subtitle'))
        if source.suffix.lower() != '.srt':
            raise SubtitleError('Only SRT sidecars can be adjusted.')
        content = decode_subtitle(source.read_bytes())
        target_fps = self.probe(video)[0]
        if not target_fps:
            raise SubtitleError('Could not determine the video frame rate.')
        result = retime_srt(
            content, request.get('sourceFps'), target_fps, request.get('offset') or 0
        )
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=source.parent,
                prefix='.' + SPACE + '-sub-',
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(result.replace('\r\n', '\n'))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, source.stat().st_mode & 0o777)
            index = 1
            while True:
                suffix = '.bak' if index == 1 else f'.bak.{index}'
                backup = source.with_name(source.name + suffix)
                try:
                    # Preserve the original inode, including any seeding hard link.
                    os.link(source, backup)
                    break
                except FileExistsError:
                    index += 1
            try:
                os.replace(temporary, source)
            except OSError:
                backup.unlink(missing_ok=True)
                raise
            return {'path': str(source), 'backup': str(backup), 'fps': target_fps}
        except OSError as error:
            raise SubtitleError(
                'Could not save adjusted subtitles. The original file was kept.'
            ) from error
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def extract(self, request):
        video, _ = self.registered(request.get('path'))
        _, streams = self.probe(video)
        selected = next(
            (item for item in streams if item['index'] == request.get('index')), None
        )
        if not selected or not selected['extractable']:
            raise SubtitleError('This embedded subtitle cannot be extracted as text.')
        code = (
            selected['language']
            if re.fullmatch(r'[a-z]{2,3}', selected['language'])
            else 'und'
        )
        target = self.target(video, code, 'embedded')
        with tempfile.NamedTemporaryFile(
            dir=video.parent, suffix='.srt', prefix='.' + SPACE + '-sub-', delete=False
        ) as stream:
            temp = Path(stream.name)
        try:
            run = subprocess.run(
                [
                    'ffmpeg',
                    '-nostdin',
                    '-v',
                    'error',
                    '-i',
                    str(video),
                    '-map',
                    f'0:{selected["index"]}',
                    '-c:s',
                    'srt',
                    '-y',
                    str(temp),
                ],
                capture_output=True,
                timeout=60,
            )
            if run.returncode:
                raise SubtitleError('Could not extract this subtitle track.')
            content = decode_subtitle(temp.read_bytes())
            return {'path': self.save(target, content, video)}
        except (OSError, subprocess.SubprocessError):
            raise SubtitleError(
                'ffmpeg is needed to extract embedded subtitles.'
            ) from None
        finally:
            temp.unlink(missing_ok=True)

    def remove(self, request):
        video, _ = self.registered(request.get('path'))
        sidecar = self.sidecar(video, request.get('subtitle'))
        with self.db() as db:
            managed = db.execute(
                'SELECT 1 FROM subtitle_managed WHERE path=? AND video_path=?',
                (str(sidecar), str(video)),
            ).fetchone()
            if not managed:
                raise SubtitleError(
                    'Only subtitles added by Movies can be removed here.'
                )
            sidecar.unlink()
            db.execute('DELETE FROM subtitle_managed WHERE path=?', (str(sidecar),))
        return {'removed': str(sidecar)}

    def play_with(self, request):
        video, _ = self.registered(request.get('path'))
        sidecar = self.sidecar(video, request.get('subtitle'))
        player = self.config().get('player', ['mpv'])
        if (
            not isinstance(player, list)
            or not all(isinstance(part, str) for part in player)
            or not player
            or Path(player[0]).name != 'mpv'
        ):
            raise SubtitleError(
                'Playing a chosen subtitle requires mpv as the configured player.'
            )
        if not shutil.which(player[0]):
            raise SubtitleError('The configured mpv player is not installed.')
        return {'command': player + ['--sub-file=' + str(sidecar), '--', str(video)]}

    def handle(self, request):
        operation = request.get('op')
        if operation not in (
            'inspect',
            'search',
            'download',
            'retime',
            'extract',
            'remove',
            'play_with',
        ):
            raise SubtitleError('Unknown subtitle request.')
        return getattr(self, operation)(request)


def main():
    from spaces.movies.worker import serve, own_process_group

    own_process_group()
    backend = SubtitleBackend()
    serve(
        backend.handle,
        errors=(SubtitleError, ValueError),
        latest=('inspect', 'search'),
        controls=('download', 'retime', 'extract', 'remove'),
    )


if __name__ == '__main__':
    main()
