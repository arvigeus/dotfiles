"""Storage namespace and private configuration of each owned media worker."""

import json
import os
from pathlib import Path

from integrations import private

SPACE = os.environ.get('QUICKSHELL_MEDIA_SPACE', 'movies')
if SPACE not in ('movies', 'series', 'games', 'books', 'music'):
    raise ValueError('Unknown media Space.')
ROOT = 'quickshell/desktop/spaces/' + SPACE
CONFIG_DIR = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / ROOT
DATA = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / ROOT
CONFIG = CONFIG_DIR / 'media.json'
CREDENTIALS = ('tmdb_key', 'omdb_key', 'mdblist_key', 'watchmode_key', 'mal_client_id')


class ConfigError(ValueError):
    """media.json cannot be used; the message is meant for the user."""


def media_config(path):
    """media.json as an object, or {} when it is absent.

    It may link into a private checkout; the opened target is checked. API keys,
    the OpenSubtitles account and the executed player command need owner-only
    access, like the shared integration credentials.
    """
    try:
        text, info = private.read(path, follow_symlinks=True)
    except FileNotFoundError:
        return {}
    except private.UnreadableFile as error:
        raise ConfigError(str(error)) from None
    try:
        config = json.loads(text)
    except ValueError:
        raise ConfigError('Cannot read media.json. Check its JSON syntax.') from None
    if not isinstance(config, dict):
        raise ConfigError('media.json must contain a JSON object.')
    account = config.get('opensubtitles')
    sensitive = any(config.get(key) for key in (*CREDENTIALS, 'player')) or (
        isinstance(account, dict)
        and any(account.get(key) for key in ('api_key', 'password'))
    )
    if sensitive and not private.owner_only(info):
        raise ConfigError(
            'media.json holds credentials or a player command: '
            'it must be owned by you with mode 0600.'
        )
    return config


def extra_library_roots(kind):
    """User-owned library locations; provisioning copies only the example."""
    key = {'movie': 'movies', 'tv': 'series'}.get(kind)
    if not key:
        return []
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / (
        'quickshell/desktop/integrations/media-library.json'
    )
    try:
        text, _ = private.read(config, follow_symlinks=False)
        settings = json.loads(text)
    except FileNotFoundError:
        return []
    except (private.UnreadableFile, ValueError) as error:
        raise ValueError(f'Cannot read {config}: {error}') from None
    if not isinstance(settings, dict):
        raise ValueError(f'{config} must contain a JSON object.')
    values = settings.get(key, [])
    if not isinstance(values, list) or any(
        not isinstance(p, str) or not p.strip() for p in values
    ):
        raise ValueError(f'{config}: {key} must be a list of directory paths.')
    roots = []
    for value in values:
        root = Path(value.replace('$HOME', str(Path.home()))).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError(
                f'Library directory does not exist or is not absolute: {value}'
            )
        root = root.resolve()
        if root not in roots:
            roots.append(root)
    return roots
