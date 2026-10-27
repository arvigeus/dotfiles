"""User-installed wallpaper command providers; catalogue logic stays in commands."""

import atexit
import hashlib
import json
import os
import re
import signal
from pathlib import Path

from spaces.pictures.command_provider import CommandRunner, safe_url
from spaces.pictures.provider_plugins import ProviderError, configured_providers

runner = CommandRunner(label='Pictures')
atexit.register(runner.close)
RESERVED = {'wallhaven', 'bing', 'wallpaper_engine'}


def configuration_file():
    root = Path(os.environ.get('XDG_CONFIG_HOME', '~/.config')).expanduser()
    if not root.is_absolute():
        root = Path.home() / '.config'
    return root / 'quickshell/desktop/spaces/pictures/pictures.json'


def configured():
    path = configuration_file()
    try:
        config = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise ValueError('Cannot read pictures.json.') from error
    if not isinstance(config, dict):
        raise ValueError('pictures.json must contain an object.')
    result = {}
    try:
        commands = configured_providers(config, path.parent)
        for row, command in zip(config.get('providers', []), commands, strict=True):
            identifier = row.get('id', '')
            if (
                not isinstance(identifier, str)
                or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', identifier)
                or identifier in RESERVED
                or identifier in result
            ):
                raise ValueError(
                    'Pictures providers need unique IDs distinct from built-in providers.'
                )
            result[identifier] = dict(command, id=identifier)
    except ProviderError as error:
        raise ValueError(str(error)) from error
    return result


def descriptors():
    return [
        {
            'id': p['id'],
            'name': p['name'],
            'search': True,
            'random': False,
            'defaultFilters': {},
            'filters': [],
        }
        for p in configured().values()
    ]


def clean_item(raw, include_disabled=False):
    if not isinstance(raw, dict):
        return None
    provider_id = raw.get('provider')
    if not isinstance(provider_id, str) or not re.fullmatch(
        r'[a-z][a-z0-9_-]{0,63}', provider_id
    ):
        return None
    provider = configured().get(provider_id)
    if not provider and include_disabled and provider_id not in RESERVED:
        provider = {
            'id': provider_id,
            'name': str(raw.get('providerName') or provider_id),
        }
    identifier, title = raw.get('id'), raw.get('title')
    kind = raw.get('kind', 'image')
    if (
        not provider
        or not isinstance(identifier, str)
        or not identifier.strip()
        or len(identifier) > 512
        or not isinstance(title, str)
        or not title.strip()
        or kind not in {'image', 'video'}
        or 'ref' not in raw
    ):
        return None
    preview = safe_url(raw.get('preview')) or safe_url(raw.get('thumbLarge'))
    try:
        dimensions = {
            key: max(0, int(raw.get(key, 0))) for key in ('width', 'height', 'fileSize')
        }
        json.dumps(raw['ref'], allow_nan=False)
    except (ValueError, TypeError, OverflowError):
        return None
    return dict(
        dimensions,
        provider=provider['id'],
        providerName=provider['name'],
        siteName=provider['name'],
        id=identifier,
        title=title.strip(),
        kind=kind,
        ref=raw['ref'],
        preview=preview,
        path=preview,
        thumbSmall=safe_url(raw.get('thumbSmall')) or preview,
        thumbLarge=safe_url(raw.get('thumbLarge')) or preview,
        url=safe_url(raw.get('url')),
        description=str(raw.get('description') or '')[:10000],
        fileType='video/mp4' if kind == 'video' else 'image/jpeg',
        colors=[],
        tags=[],
    )


def call(provider, request):
    try:
        return runner.call(provider, request)
    except ProviderError as error:
        raise ValueError(str(error)) from error


def browse(args):
    provider = configured()[args['provider']]
    payload = call(
        provider,
        {
            'op': 'browse',
            'query': str(args.get('query') or '')[:500],
            'page': args.get('page', 1),
            'filters': args.get('filters', {}),
        },
    )
    rows = payload.get('items')
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError(
            'Wallpaper provider must return an items list of at most 500 entries.'
        )
    items = []
    for row in rows:
        item = (
            clean_item(dict(row, provider=provider['id']))
            if isinstance(row, dict)
            else None
        )
        if not item:
            raise ValueError('Wallpaper provider returned an invalid item.')
        items.append(item)
    page = payload.get('next', 0)
    if type(page) not in (str, int) or (isinstance(page, int) and page < 0):
        raise ValueError('Wallpaper provider returned an invalid pagination token.')
    return {'items': items, 'next': page, 'total': payload.get('total', len(items))}


def resolve(item):
    provider = configured().get(item['provider'])
    if not provider:
        raise ValueError('This wallpaper provider is no longer configured.')
    payload = call(provider, {'op': 'resolve', 'ref': item['ref']})
    url = safe_url(payload.get('url'))
    headers = payload.get('headers', {})
    if (
        not url
        or not isinstance(headers, dict)
        or not all(
            isinstance(k, str)
            and re.fullmatch(r'[A-Za-z0-9-]+', k)
            and isinstance(v, str)
            and not any(ord(c) < 32 for c in v)
            for k, v in headers.items()
        )
    ):
        raise ValueError(
            'Wallpaper provider returned an invalid download URL or headers.'
        )
    return url, headers


def cache_id(item):
    return hashlib.sha256(item['id'].encode()).hexdigest()


def install_shutdown_handler(cleanup=None):
    os.setpgid(0, 0)

    def shutdown(signum, frame):
        runner.close()
        if cleanup:
            cleanup()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.killpg(os.getpid(), signal.SIGTERM)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
