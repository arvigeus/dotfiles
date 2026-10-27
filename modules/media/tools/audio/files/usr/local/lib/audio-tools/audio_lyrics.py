"""Shared, explicit LRCLIB-compatible lyric lookups for Audio tools and Music."""

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from threading import Lock

DEFAULT_CONFIG = {
    'version': 1,
    'providers': [{'name': 'LRCLIB', 'base_url': 'https://lrclib.net/api'}],
}
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_LYRICS = 200000
_cooldowns = {}
_cooldown_lock = Lock()


class LyricsError(ValueError):
    pass


def config_path():
    return (
        Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
        / 'audio-tools/lyrics.json'
    )


def read_config(path=None):
    try:
        with Path(path or config_path()).open('rb') as stream:
            body = stream.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError()
        data = json.loads(body)
    except FileNotFoundError:
        data = DEFAULT_CONFIG
    except (OSError, ValueError):
        raise LyricsError(
            'The shared lyrics configuration could not be read.'
        ) from None
    if not isinstance(data, dict) or data.get('version') != 1:
        raise LyricsError('The shared lyrics configuration requires version 1.')
    providers = data.get('providers')
    if (
        not isinstance(providers, list)
        or len(providers) > 8
        or any(not isinstance(p, dict) for p in providers)
    ):
        raise LyricsError('Lyrics providers must be an array of up to eight objects.')
    return providers


def provider_url(provider, song):
    base = str(provider.get('base_url') or 'https://lrclib.net/api').strip().rstrip('/')
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme not in ('http', 'https')
        or not parsed.netloc
        or parsed.username is not None
        or parsed.query
        or parsed.fragment
        or any(c in base for c in '\r\n\0')
    ):
        raise LyricsError(
            'A lyrics provider URL must use HTTP or HTTPS without credentials, query or fragment.'
        )
    endpoint = base if base.endswith('/get') else base + '/get'
    params = {
        'track_name': str(song.get('title') or '').strip(),
        'artist_name': str(song.get('artist') or '').strip(),
    }
    album = str(song.get('album') or '').strip()
    if album and album.casefold() != 'unknown album':
        params['album_name'] = album
    try:
        duration = float(song.get('duration') or 0)
    except (ValueError, TypeError):
        duration = 0
    if math.isfinite(duration) and duration > 0:
        params['duration'] = str(round(duration))
    return endpoint + '?' + urllib.parse.urlencode(params)


def provider_headers(provider):
    values = provider.get('headers') or {}
    if not isinstance(values, dict):
        raise LyricsError('Lyrics provider headers must be an object.')
    headers = {
        'Accept': 'application/json',
        'User-Agent': 'Desktop Audio tools',
        'Lrclib-Client': 'Desktop Audio tools',
    }
    values = dict(values)
    key = str(provider.get('api_key') or '').strip()
    if key:
        values[str(provider.get('api_key_header') or 'Authorization').strip()] = (
            str(provider.get('api_key_prefix', 'Bearer ')) + key
        )
    for name, value in values.items():
        name, value = str(name).strip(), str(value).strip()
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or any(
            c in value for c in '\r\n\0'
        ):
            raise LyricsError('A lyrics provider contains invalid HTTP headers.')
        for previous in list(headers):
            if previous.casefold() == name.casefold():
                del headers[previous]
        headers[name] = value
    return headers


class ProviderRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        old, new = (
            urllib.parse.urlsplit(request.full_url),
            urllib.parse.urlsplit(newurl),
        )
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            fp.close()
            raise LyricsError('A lyrics provider redirected to a different origin.')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def request_json(url, headers):
    host = urllib.parse.urlsplit(url).netloc.lower()
    with _cooldown_lock:
        if time.time() < _cooldowns.get(host, 0):
            raise LyricsError('The lyrics provider is rate-limited; try again later.')
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.build_opener(ProviderRedirect()).open(
            request, timeout=16
        ) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise LyricsError('A lyrics provider returned an oversized response.')
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 404:
            return None
        if error.code == 429:
            try:
                retry_after = min(
                    86400, max(1, int(error.headers.get('Retry-After') or 60))
                )
            except (TypeError, ValueError):
                retry_after = 60
            with _cooldown_lock:
                _cooldowns[host] = time.time() + retry_after
            raise LyricsError(
                'The lyrics provider is rate-limited; try again later.'
            ) from None
        if error.code in (502, 503, 504):
            raise LyricsError('A lyrics provider is temporarily unavailable.') from None
        raise LyricsError(
            'A lyrics provider returned HTTP ' + str(error.code) + '.'
        ) from None
    except urllib.error.URLError:
        raise LyricsError('Could not connect to a lyrics provider.') from None
    except (TimeoutError, OSError):
        raise LyricsError('A lyrics provider could not complete the request.') from None
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise LyricsError('A lyrics provider returned unreadable JSON.') from None


def from_response(response):
    if not isinstance(response, dict):
        return ''
    plain = response.get('plainLyrics')
    synced = response.get('syncedLyrics')
    if (
        plain is not None
        and not isinstance(plain, str)
        or synced is not None
        and not isinstance(synced, str)
    ):
        raise LyricsError('A lyrics provider returned invalid lyrics.')
    text = (plain or '').strip()
    if not text:
        text = '\n'.join(
            filter(
                None,
                (
                    re.sub(
                        r'\[(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]', '', line
                    ).strip()
                    for line in (synced or '').splitlines()
                ),
            )
        ).strip()
    if len(text) > MAX_LYRICS or '\0' in text:
        raise LyricsError('A lyrics provider returned invalid or oversized lyrics.')
    return text


def lookup(song, providers=None):
    if not isinstance(song, dict):
        raise LyricsError('Invalid song for lyrics lookup.')
    if (
        not str(song.get('title') or '').strip()
        or not str(song.get('artist') or '').strip()
    ):
        raise LyricsError('Set the title and artist before fetching lyrics.')
    providers = read_config() if providers is None else providers
    if not providers:
        raise LyricsError('No lyrics provider is configured.')
    failures = []
    for index, provider in enumerate(providers):
        try:
            lyrics = from_response(
                request_json(provider_url(provider, song), provider_headers(provider))
            )
        except LyricsError as error:
            failures.append(error)
            continue
        if lyrics:
            return dict(
                available=True,
                lyrics=lyrics,
                provider=str(
                    provider.get('name') or 'Lyrics provider ' + str(index + 1)
                ),
            )
    if failures:
        raise failures[-1]
    return dict(available=False, lyrics='', provider='')


def main():
    try:
        payload = sys.stdin.buffer.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise LyricsError('Invalid lyrics lookup request.')
        result = lookup(json.loads(payload))
    except (OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    'error': str(error)
                    if isinstance(error, LyricsError)
                    else 'Invalid lyrics lookup request.'
                }
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
