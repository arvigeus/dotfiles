"""Installed Wallpaper Engine catalogue and optional session playback controller.

Wallpiper owns rendering and its daemon. This adapter uses only its public CLI;
the shell yields to verified Hyprland background surfaces, never launch order.
"""

import ctypes
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spaces.pictures import video_wallpaper, workshop
from spaces.pictures.storage import atomic_write
from spaces.pictures.wallpaper import update_lock_background

PROVIDER: dict[str, Any] = {
    'id': 'wallpaper_engine',
    'name': 'Wallpaper Engine',
    'search': True,
    'random': False,
    'defaultFilters': {
        'source': 'installed',
        'type': '',
        'tag': '',
        'sorting': 'title',
        'workshopTag': '',
        'workshopSort': 'popular',
    },
    'filters': [
        {
            'key': 'type',
            'label': 'Type',
            'width': 150,
            'options': [
                {'label': 'All types', 'value': ''},
                {'label': 'Scene', 'value': 'scene'},
                {'label': 'Video', 'value': 'video'},
                {'label': 'Web', 'value': 'web'},
            ],
        },
        {
            'key': 'tag',
            'label': 'Tag',
            'width': 180,
            'when': {'key': 'source', 'value': 'installed'},
            'options': [
                {'label': 'All tags', 'value': ''},
            ],
        },
        {
            'key': 'sorting',
            'label': 'Sort',
            'width': 150,
            'when': {'key': 'source', 'value': 'installed'},
            'options': [
                {'label': 'Title A–Z', 'value': 'title'},
                {'label': 'Title Z–A', 'value': 'title_desc'},
            ],
        },
        {
            'key': 'workshopTag',
            'label': 'Tag',
            'width': 180,
            'when': {'key': 'source', 'value': 'workshop'},
            'options': [{'label': 'All tags', 'value': ''}]
            + [{'label': tag, 'value': tag} for tag in workshop.TAGS],
        },
        {
            'key': 'workshopSort',
            'label': 'Sort',
            'width': 150,
            'when': {'key': 'source', 'value': 'workshop'},
            'options': [
                {'label': 'Popular', 'value': 'popular'},
                {'label': 'Newest', 'value': 'newest'},
                {'label': 'Trending this week', 'value': 'trending'},
                {'label': 'Relevance', 'value': 'relevance'},
            ],
        },
    ],
}
WORKSHOP_ID = re.compile(r'^[0-9]{1,20}$')
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}
STARTUP_TIMEOUT = 45
RECOVERY_TIMEOUT = 15
MAX_RESTARTS = 3
HEALTHY_SECONDS = 60
PR_SET_PDEATHSIG = 1
_prctl = ctypes.CDLL(None).prctl


class TransientError(ValueError):
    """A running session may recover without changing its saved selection."""


def config_dir():
    value = Path(os.environ.get('XDG_CONFIG_HOME', '~/.config')).expanduser()
    return (
        value if value.is_absolute() else Path.home() / '.config'
    ) / 'quickshell/desktop/spaces/pictures'


def read_setting():
    try:
        value = json.loads((config_dir() / 'wallpaper.json').read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def state_file():
    identity = hashlib.sha256(str(config_dir()).encode()).hexdigest()[:12]
    base = Path(os.environ.get('XDG_RUNTIME_DIR') or '/tmp')
    if not base.is_absolute():
        base = Path('/tmp')
    folder = base / f'desktop-wallpaper-{os.getuid()}-{identity}'
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = folder.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise ValueError(
            'Wallpaper runtime directory must be private and owned by this user.'
        )
    return folder / 'state.json'


def read_state():
    try:
        value = json.loads(state_file().read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def process_identity(pid):
    try:
        # The start time prevents an unrelated process reusing a recorded PID.
        fields = Path(f'/proc/{int(pid)}/stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] in {'Z', 'X'}:
            # Wine/Chromium can exit their main thread while other threads
            # keep the process and its X11 windows alive.
            tasks = Path(f'/proc/{int(pid)}/task')
            for task in tasks.iterdir():
                try:
                    if task.joinpath('stat').read_text().rsplit(')', 1)[1].split()[
                        0
                    ] not in {
                        'Z',
                        'X',
                    }:
                        return fields[19]
                except (OSError, ValueError, IndexError):
                    continue
            return ''
        return fields[19]
    except (OSError, ValueError, IndexError):
        return ''


def runtime_alive(state):
    return (
        bool(state.get('identity'))
        and process_identity(state.get('pid', 0)) == state['identity']
    )


def die_with_worker():
    """Popen preexec_fn: SIGTERM the child when this worker dies.

    Quickshell SIGKILLs workers on unload and shell exit, so the worker cannot
    stop its renderer itself; the renderer's own SIGTERM handler cleans up.
    """
    _prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)


def open_lock(path):
    descriptor = os.open(
        path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        os.close(descriptor)
        raise ValueError('Wallpaper lock must be a regular file owned by this user.')
    return os.fdopen(descriptor, 'a')


def wait_idle(timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = read_state()
        if state.get('status') == 'idle' or not runtime_alive(state):
            return
        time.sleep(0.1)
    raise ValueError(
        "Wallpaper Engine shutdown timed out. Check the shell's wallpaper runtime."
    )


@contextmanager
def control_lock():
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with open_lock(folder / '.engine-control.lock') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def library_paths():
    candidates = []
    try:
        config = json.loads((config_dir() / 'pictures.json').read_text())
        paths = config.get('wallpaper_engine', {}).get('library_paths', [])
        if isinstance(paths, list):
            candidates.extend(path for path in paths if isinstance(path, str))
    except (OSError, ValueError, AttributeError):
        pass
    if os.environ.get('WALLPIPER_STEAM_ROOT'):
        candidates.append(os.environ['WALLPIPER_STEAM_ROOT'])
    candidates.extend(
        [
            '~/.local/share/Steam',
            '~/.steam/steam',
            '~/.steam/root',
            '~/.var/app/com.valvesoftware.Steam/.local/share/Steam',
        ]
    )
    roots = []
    for value in candidates:
        root = Path(value).expanduser().resolve()
        if root.is_dir() and root not in roots:
            roots.append(root)
    # Steam's library file has named, quoted path fields. Do not interpret the
    # rest of this file or rely on the human-readable wallpiperctl list output.
    for root in list(roots):
        try:
            content = (root / 'steamapps/libraryfolders.vdf').read_text()
        except OSError:
            continue
        for value in re.findall(r'"path"\s*"((?:\\.|[^"\\])*)"', content):
            path = (
                Path(value.replace('\\"', '"').replace('\\\\', '\\'))
                .expanduser()
                .resolve()
            )
            if path.is_dir() and path not in roots:
                roots.append(path)
    return roots


def workshop_folders():
    for root in library_paths():
        folder = root / 'steamapps/workshop/content/431960'
        if folder.is_dir():
            yield folder


def load_project(folder, child):
    """Return (project.json, metadata) for one installed item, or None."""
    project = child / 'project.json'
    try:
        if not project.resolve().is_relative_to(folder.resolve()):
            return None
        if project.stat().st_size > 1024 * 1024:
            return None
        metadata = json.loads(project.read_text())
    except (OSError, ValueError):
        return None
    return (project.resolve(), metadata) if isinstance(metadata, dict) else None


def projects():
    result = {}
    for folder in workshop_folders():
        for child in sorted(folder.iterdir()):
            if WORKSHOP_ID.fullmatch(child.name) and child.name not in result:
                entry = load_project(folder, child)
                if entry:
                    result[child.name] = entry
    return result


def installed_project(identifier):
    for folder in workshop_folders():
        entry = load_project(folder, folder / identifier)
        if entry:
            return entry
    return None


def preview_path(project, metadata):
    value = metadata.get('preview')
    if not isinstance(value, str) or not value:
        return None
    path = (project.parent / value).resolve()
    return (
        path
        if (
            path.is_relative_to(project.parent)
            and path.is_file()
            and path.suffix.lower() in IMAGE_SUFFIXES
        )
        else None
    )


def project_tags(metadata):
    raw = metadata.get('tags', [])
    if not isinstance(raw, list):
        return []
    tags = {}
    for value in raw[:100]:
        if isinstance(value, str):
            label = ' '.join(value.split())[:80]
            if label:
                tags.setdefault(label.casefold(), label)
    return list(tags.values())


def descriptor():
    provider = dict(
        PROVIDER,
        filters=[
            dict(field, options=list(field['options'])) for field in PROVIDER['filters']
        ],
    )
    provider['defaultFilters'] = dict(
        PROVIDER['defaultFilters'],
        source='workshop' if workshop.api_key(config_dir()) else 'installed',
    )
    tags = {}
    for _project, metadata in projects().values():
        for label in project_tags(metadata):
            tags.setdefault(label.casefold(), label)
    provider['filters'][1]['options'].extend(
        {'label': tags[key], 'value': key} for key in sorted(tags)[:500]
    )
    return provider


def item_for(identifier, installed, saved=None):
    entry = installed.get(identifier)
    if entry:
        project, metadata = entry
        preview = preview_path(project, metadata)
        title = str(metadata.get('title') or identifier)[:200]
        kind = str(metadata.get('type') or 'Wallpaper')[:40].capitalize()
        tags = project_tags(metadata)
        description = str(metadata.get('description') or '')[:4000]
        wallpaper_type = str(metadata.get('type') or '').casefold()
        if wallpaper_type not in {'scene', 'video', 'web'}:
            wallpaper_type = 'other'
    else:
        preview = None
        title = str((saved or {}).get('title') or identifier)[:200]
        tags = project_tags(saved or {})
        description = str((saved or {}).get('description') or '')[:4000]
        wallpaper_type = next(
            (
                tag.casefold()
                for tag in tags
                if tag.casefold() in {'scene', 'video', 'web'}
            ),
            'other',
        )
        kind = wallpaper_type.capitalize()
    image = (
        preview.as_uri()
        if preview
        else workshop.thumbnail((saved or {}).get('preview'))
    )
    full_image = workshop.original_preview((saved or {}).get('path')) or image
    return {
        'provider': 'wallpaper_engine',
        'providerName': 'Wallpaper Engine',
        'id': identifier,
        'title': title,
        'path': full_image,
        'preview': image,
        'thumbLarge': image,
        'url': 'https://steamcommunity.com/sharedfiles/filedetails/?id=' + identifier,
        'siteName': 'Steam Workshop',
        'metadata': [{'label': 'Type', 'value': kind}]
        + ([{'label': 'Library', 'value': 'Not downloaded'}] if not entry else [])
        + ([{'label': 'Tags', 'value': ', '.join(tags[:8])}] if tags else []),
        'type': wallpaper_type,
        'tags': tags,
        'description': description,
        'installed': bool(entry),
        'width': 0,
        'height': 0,
    }


def clean_item(raw):
    identifier = str(raw.get('id', ''))
    if not WORKSHOP_ID.fullmatch(identifier):
        return None
    # Resolve trusted local files again. Never accept executable/project paths
    # or arbitrary file:// previews from a browser request or favorite record.
    entry = installed_project(identifier)
    return item_for(identifier, {identifier: entry} if entry else {}, raw)


def browse(args):
    filters = args.get('filters') if isinstance(args.get('filters'), dict) else {}
    if filters.get('source') == 'workshop':
        rows, next_cursor, total = workshop.query(config_dir(), args)
        installed = projects()
        items = []
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get('result') != 1
                or row.get('consumer_appid') != workshop.APP_ID
            ):
                continue
            identifier = str(row.get('publishedfileid', ''))
            if not WORKSHOP_ID.fullmatch(identifier):
                continue
            raw_tags = row.get('tags', [])
            tags = (
                [
                    tag['tag']
                    for tag in raw_tags[:100]
                    if isinstance(tag, dict) and isinstance(tag.get('tag'), str)
                ]
                if isinstance(raw_tags, list)
                else []
            )
            item = item_for(
                identifier,
                installed,
                {
                    'title': row.get('title'),
                    'description': row.get('short_description'),
                    'tags': tags,
                    'preview': row.get('preview_url'),
                    'path': workshop.full_preview(row),
                },
            )
            items.append(item)
        return {'items': items, 'next': next_cursor, 'total': total}
    installed = projects()
    items = [item_for(identifier, installed) for identifier in installed]
    query = str(args.get('query') or '').strip().casefold()
    if query:
        items = [
            item
            for item in items
            if query
            in ' '.join(
                [item['title'], item['id'], item['description'], *item['tags']]
            ).casefold()
        ]
    kind = str(filters.get('type') or '')
    if kind in {'scene', 'video', 'web', 'other'}:
        items = [item for item in items if item['type'] == kind]
    tag = str(filters.get('tag') or '').casefold()
    if tag:
        items = [
            item
            for item in items
            if tag in [label.casefold() for label in item['tags']]
        ]
    items.sort(
        key=lambda item: (item['title'].casefold(), item['id']),
        reverse=filters.get('sorting') == 'title_desc',
    )
    return {'items': items, 'next': 0, 'total': len(items)}


def open_workshop(args):
    identifier = str(args.get('workshopId', ''))
    if not WORKSHOP_ID.fullmatch(identifier):
        raise ValueError('Invalid Steam Workshop item.')
    executable = shutil.which('steam')
    if not executable:
        raise ValueError(
            "Steam is not on the shell's PATH. Make the Steam executable available and try again."
        )
    # Invoke Steam directly: desktop URL handlers may discard the URI or start
    # an unrelated Big Picture launcher. The page is fixed, not caller-supplied.
    uri = (
        'steam://openurl/https://steamcommunity.com/sharedfiles/filedetails/?id='
        + identifier
    )
    try:
        process = subprocess.Popen(
            [executable, uri],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            exit_code = process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            exit_code = None
        if exit_code not in (None, 0):
            raise ValueError(
                'Steam could not open the Workshop page. Check the Steam client and try again.'
            )
    except OSError:
        raise ValueError(
            'Steam could not open the Workshop page. Check the Steam client and try again.'
        ) from None
    return {
        'message': 'Sent to Steam. Click Subscribe there; Pictures will detect the completed download.'
    }


def engine_executable():
    """Find the renderer without launching Steam or Wallpaper Engine."""
    configured_executable = os.environ.get('WALLPIPER_WE_EXE', '')
    if configured_executable:
        path = Path(configured_executable).expanduser()
        return path.resolve() if path.is_file() else None
    for root in library_paths():
        common = (root / 'steamapps/common').resolve()
        folder = common / 'wallpaper_engine'
        try:
            manifest = (root / 'steamapps/appmanifest_431960.acf').read_text()
            match = re.search(r'"installdir"\s*"([^"\\]+)"', manifest)
            if match:
                candidate = (common / match[1]).resolve()
                if candidate.is_relative_to(common):
                    folder = candidate
        except OSError:
            pass
        # Current releases put the renderer in distribution; older installs
        # have it directly in the application's directory.
        for relative in ('wallpaper64.exe', 'distribution/wallpaper64.exe'):
            path = folder / relative
            if path.is_file():
                return path.resolve()
    return None


def configured_proton():
    if os.environ.get('WALLPIPER_PROTON_BIN'):
        return os.environ['WALLPIPER_PROTON_BIN']
    try:
        config = json.loads((config_dir() / 'pictures.json').read_text())
        value = config.get('wallpaper_engine', {}).get('proton_bin', '')
        return value if isinstance(value, str) else ''
    except (OSError, ValueError, AttributeError):
        return ''


def proton_executable():
    configured = configured_proton()
    if configured:
        path = Path(configured).expanduser()
        return path.resolve() if path.is_file() and os.access(path, os.X_OK) else None
    for root in library_paths():
        candidates = sorted(
            (root / 'compatibilitytools.d').glob('*/proton'), reverse=True
        )
        candidates += sorted(
            (root / 'steamapps/common').glob('Proton */proton'), reverse=True
        )
        for path in candidates:
            if path.is_file() and os.access(path, os.X_OK):
                return path.resolve()
    return None


def installation_status(item):
    engine_installed = engine_executable() is not None
    wallpiper_installed = bool(
        shutil.which('wallpiperd') and shutil.which('wallpiperctl')
    )
    messages = []
    if not engine_installed:
        messages.append(
            'Wallpaper Engine is not installed or could not be found. Install Wallpaper Engine in Steam, then wait for its download to finish. Subscribing to a wallpaper does not install the application.'
        )
    if not wallpiper_installed:
        messages.append(
            'Install Wallpiper with its Hyprland portal (Arch: paru -S wallpiper-hyprland).'
        )
    if proton_executable() is None:
        messages.append(
            "Proton is not installed, executable, or could not be found. Install Proton in Steam's Tools library or configure a GE-Proton installation."
        )
    if not item.get('installed'):
        messages.append(
            'Steam has not downloaded this wallpaper yet. Check its Workshop download in Steam and wait for it to finish.'
        )
    ready = not messages
    setting, state = read_setting(), read_state()
    if (
        setting.get('mode') == 'wallpaper_engine'
        and str(setting.get('workshop_id')) == str(item.get('id'))
        and state.get('selection') == setting.get('selection')
        and state.get('status') == 'error'
        and state.get('error')
    ):
        messages.append(str(state['error']))
    # Playback failure is visible in Pictures, but Apply must remain available
    # when the installation is ready so the user can explicitly retry.
    return {'wallpaper': item, 'ready': ready, 'message': ' '.join(messages)}


def control(*args, environment=None):
    executable = shutil.which('wallpiperctl')
    if not executable:
        raise ValueError(
            'Wallpaper Engine requires wallpiperctl. Install Wallpiper; the shell starts its Hyprland portal on Apply.'
        )
    try:
        result = subprocess.run(
            [executable, *map(str, args)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TransientError('Wallpaper Engine control failed or timed out.') from error
    if result.returncode:
        raise TransientError(
            (result.stderr or result.stdout).strip()[:400]
            or 'Wallpaper Engine did not respond. Check the running Wallpiper session.'
        )


def hypr_query(subject):
    executable = shutil.which('hyprctl')
    if not executable or not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        raise ValueError(
            'Wallpaper Engine integration currently requires a Hyprland session.'
        )
    try:
        result = subprocess.run(
            [executable, subject, '-j'],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode:
            raise ValueError()
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise TransientError(
            'Could not inspect the Hyprland wallpaper surfaces.'
        ) from error


def portal_surfaces(layers, visible_only=True):
    """Only actual Background-layer surfaces can replace our desktop."""
    result = {}
    if not isinstance(layers, dict):
        return result
    for name, monitor in layers.items():
        if not isinstance(monitor, dict):
            continue
        levels = monitor.get('levels', {})
        background = levels.get('0', []) if isinstance(levels, dict) else []
        surfaces = [
            surface
            for surface in background
            if isinstance(surface, dict)
            and surface.get('namespace') == 'wallpiper-portal-hyprland'
            and (not visible_only or surface.get('alpha', 1) > 0)
            and surface.get('w', 0) > 0
            and surface.get('h', 0) > 0
        ]
        if surfaces:
            result[name] = [str(surface.get('address', '')) for surface in surfaces]
    return result


def visible_fullscreen(monitors, clients):
    for monitor in monitors:
        if monitor.get('disabled') or monitor.get('dpmsStatus') is False:
            continue
        special = monitor.get('specialWorkspace', {}).get('id', 0)
        workspace = special or monitor.get('activeWorkspace', {}).get('id')
        for client in clients:
            if (
                client.get('monitor') == monitor.get('id')
                and client.get('workspace', {}).get('id') == workspace
                and client.get('mapped', True)
                and not client.get('hidden', False)
            ):
                # Hyprland's internal state distinguishes maximized (1) from
                # true fullscreen (2). Older IPC versions use a boolean.
                state = client.get('fullscreen', 0)
                if state is True or (type(state) is int and bool(state & 2)):
                    return True
    return False


def restored_slots(project, metadata, environment):
    """Recognize only concrete native selections, never assume startup restored ours."""
    renderer = Path(environment.get('WALLPIPER_WE_EXE', ''))
    try:
        path = renderer.parent / 'config.json'
        if path.stat().st_size > 4 * 1024 * 1024:
            return set()
        native = json.loads(path.read_text())
        selected = native['steamuser']['general']['wallpaperconfig'][
            'selectedwallpapers'
        ]
        asset = str(metadata.get('file', ''))
        if not asset:
            return set()
        candidates = {project.resolve(), (project.parent / asset).resolve()}
        # Installed scenes commonly name scene.json while shipping scene.pkg.
        if metadata.get('type', '').lower() == 'scene':
            candidates.add((project.parent / asset).with_suffix('.pkg').resolve())
        slots = set()
        for name, value in selected.items():
            match = re.fullmatch(r'Monitor([0-9]+)', name)
            if not match or not isinstance(value, dict):
                continue
            filename = value.get('file', '')
            if not isinstance(filename, str):
                continue
            filename = filename.replace('\\', '/')
            if filename[:3].lower() == 'z:/':
                filename = filename[2:]
            if Path(filename).is_absolute() and Path(filename).resolve() in candidates:
                slots.add(int(match[1]))
        return slots
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return set()


NATIVE_PLAYBACK_RULES = ('playbacksleep', 'playbackfullscreen', 'playbackmaximized')


def native_playback_policy_file():
    return config_dir() / '.engine-native-playback.json'


def native_user_settings(native):
    try:
        user = (
            native.setdefault('steamuser', {})
            .setdefault('general', {})
            .setdefault('user', {})
        )
        if not isinstance(user, dict):
            raise TypeError
        return user
    except (AttributeError, TypeError) as error:
        raise ValueError(
            'Invalid Wallpaper Engine native settings. Check config.json.'
        ) from error


def read_native_config(path):
    if not path.exists():
        # Match Wallpiper's initial settings while installing our playback policy.
        return {
            'steamuser': {
                'general': {
                    'user': {
                        'adjustdwmcolormode': 'disabled',
                        'uihardwareacceleration': False,
                    }
                }
            }
        }
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Wallpaper Engine config.json is too large.')
    native = json.loads(path.read_text())
    if not isinstance(native, dict):
        raise ValueError('Invalid Wallpaper Engine config.json.')
    return native


def restore_native_playback_policy():
    journal = native_playback_policy_file()
    if not journal.exists():
        return
    record = json.loads(journal.read_text())
    if not isinstance(record, dict):
        record = {}
    originals = record.get('originals')
    path = Path(record['path']) if isinstance(record.get('path'), str) else None
    if (
        not isinstance(originals, dict)
        or not originals
        or any(
            key not in NATIVE_PLAYBACK_RULES
            or not isinstance(value, dict)
            or type(value.get('present')) is not bool
            or 'value' not in value
            for key, value in originals.items()
        )
        or path is None
        or not path.is_absolute()
        or path.name != 'config.json'
    ):
        raise ValueError('Invalid Wallpaper Engine playback policy record.')
    if path.exists():
        native = read_native_config(path)
        user = native_user_settings(native)
        # Preserve subsequent native/user edits and all unrelated settings.
        changed = False
        for key, original in originals.items():
            if user.get(key) == 'run':
                if original['present']:
                    user[key] = original['value']
                else:
                    user.pop(key, None)
                changed = True
        if changed:
            atomic_write(path, json.dumps(native, indent=2) + '\n')
    journal.unlink()


def install_native_playback_policy(renderer):
    path = renderer.parent / 'config.json'
    native = read_native_config(path)
    user = native_user_settings(native)
    originals = {
        key: {'present': key in user, 'value': user.get(key)}
        for key in NATIVE_PLAYBACK_RULES
        if user.get(key) != 'run'
    }
    if not originals:
        return
    # Windows window/display heuristics cannot reliably describe a Wayland
    # desktop. Disable native sleep/fullscreen/maximized decisions while the
    # compositor-owned controller handles fullscreen and physical DPMS instead.
    atomic_write(
        native_playback_policy_file(),
        json.dumps({'path': str(path.absolute()), 'originals': originals}) + '\n',
    )
    user.update({key: 'run' for key in NATIVE_PLAYBACK_RULES})
    atomic_write(path, json.dumps(native, indent=2) + '\n')


def crash_dumps(renderer):
    """Fingerprint dumps before launch; old crashes must not reject a fresh Apply."""
    result = {}
    if renderer is None:
        return result
    for path in Path(renderer).parent.glob('wallpaper*.mdmp'):
        try:
            info = path.stat()
            result[str(path)] = (info.st_ino, info.st_mtime_ns, info.st_size)
        except OSError:
            continue
    return result


def apply_project(identifier, count, environment=None, *, restored=False):
    entry = installed_project(identifier)
    if not entry:
        raise ValueError('This Wallpaper Engine wallpaper is no longer installed.')
    project, metadata = entry
    # The same choice is applied to all slots; compositor IDs are not Wallpaper
    # Engine slot IDs, and must never be passed as if they were interchangeable.
    existing = (
        restored_slots(project, metadata, environment or {}) if restored else set()
    )
    for slot in range(count):
        if slot in existing:
            continue
        control('set', str(project), slot, environment=environment)
    return preview_path(project, metadata)


def apply(item):
    status = installation_status(item)
    if not status['ready']:
        raise ValueError(status['message'])
    hypr_query('monitors')
    selection = uuid.uuid4().hex
    with control_lock():
        previous = read_setting()
        atomic_write(
            config_dir() / 'wallpaper.json',
            json.dumps(
                {
                    'mode': 'wallpaper_engine',
                    'workshop_id': item['id'],
                    'selection': selection,
                    'image': previous.get('image', ''),
                }
            )
            + '\n',
        )
    # The session controller, not the Pictures worker, owns the daemon. Wait for
    # its acknowledgement so missing dependencies/startup failures reach Apply.
    deadline = time.monotonic() + 60
    error = 'Wallpaper Engine did not start. Ensure the desktop shell is running.'
    while time.monotonic() < deadline:
        state = read_state()
        if state.get('selection') == selection:
            if state.get('error'):
                error = str(state['error'])
            if state.get('status') == 'ready':
                return {
                    'path': item.get('path', ''),
                    'service': 'Wallpaper Engine',
                    'message': 'Wallpaper Engine applied. Lock screen uses a still image.',
                }
            if state.get('status') == 'error':
                error = state.get('error') or error
                break
        if read_setting().get('selection') != selection:
            raise ValueError('Wallpaper selection changed before Apply completed.')
        time.sleep(0.1)
    with control_lock():
        if (
            previous.get('mode') not in {'wallpaper_engine', 'video'}
            and read_setting().get('selection') == selection
        ):
            atomic_write(config_dir() / 'wallpaper.json', json.dumps(previous) + '\n')
    # Restoring an animated selection here triggers another renderer launch and
    # clears its failure latch. Keep this failed request until explicit Apply;
    # its saved still image continues to supply the desktop fallback.
    if previous.get('mode') not in {'wallpaper_engine', 'video'}:
        wait_idle()
    raise ValueError(error)


def existing_engine():
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            name = (path / 'comm').read_text().strip()
            if name in {'wallpiperd', 'wallpaper64.exe'} and process_identity(
                path.name
            ):
                return True
        except OSError:
            continue
    return False


def owned_processes(marker):
    """Track only our daemon's inherited marker, including reparented Wine helpers."""
    result = {}
    if not marker:
        return result
    expected = ('DESKTOP_WALLPAPER_OWNER=' + marker).encode()
    for path in Path('/proc').iterdir():
        if not path.name.isdigit() or int(path.name) == os.getpid():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            try:
                environment = (path / 'environ').read_bytes()
            except ProcessLookupError:
                environment = b''
            if not environment:
                for task in (path / 'task').iterdir():
                    try:
                        environment = task.joinpath('environ').read_bytes()
                    except OSError:
                        continue
                    if environment:
                        break
            if expected in environment.split(b'\0'):
                identity = process_identity(path.name)
                if identity:
                    result[int(path.name)] = identity
        except OSError:
            continue
    return result


def signal_owned(processes, signum):
    for pid, identity in processes.items():
        if identity and process_identity(pid) == identity:
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                pass


def reap_owned(owner):
    """Reconcile detached helpers, even after their controller was SIGKILLed."""
    # Rescan during teardown: Wine can create/reparent helpers after the first
    # snapshot. Resume stopped renderers so graceful termination can run.
    signalled = {}
    deadline = time.monotonic() + 2
    while True:
        remaining = owned_processes(owner)
        if not remaining:
            return
        new = {
            pid: identity
            for pid, identity in remaining.items()
            if signalled.get(pid) != identity
        }
        signal_owned(new, signal.SIGCONT)
        signal_owned(new, signal.SIGTERM)
        signalled.update(new)
        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    deadline = time.monotonic() + 2
    while remaining:
        signal_owned(remaining, signal.SIGKILL)
        if time.monotonic() >= deadline:
            raise ValueError(
                'Owned wallpaper processes could not be stopped. Check daemon.log.'
            )
        time.sleep(0.05)
        remaining = owned_processes(owner)


def dismiss_owned_picker(owned):
    """Pictures owns selection; Wine's Chromium picker must not become a desktop window."""
    for pid, identity in owned.items():
        try:
            process = Path(f'/proc/{pid}')
            command = process.joinpath('cmdline').read_bytes().lower()
            picker = b'wallpaperui.exe' in command
            if not command:
                picker = any(
                    task.joinpath('comm').read_text().strip() == 'wallpaperui.exe'
                    for task in process.joinpath('task').iterdir()
                )
            if picker:
                if identity and process_identity(pid) == identity:
                    os.kill(pid, signal.SIGKILL)
        except (OSError, ValueError):
            continue


class Runtime:
    def __init__(self):
        state_file()  # Validate the private runtime directory before writing ownership.
        config_dir().mkdir(parents=True, exist_ok=True)
        # The lease/journal share the config identity, even if XDG_RUNTIME_DIR
        # changes between shell launches or its session directory is removed.
        self.lease = open_lock(config_dir() / '.engine-runtime.lock')
        deadline = time.monotonic() + 20
        while True:
            try:
                fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                # A shell reload may start our replacement before the previous
                # worker has finished graceful daemon cleanup.
                if time.monotonic() >= deadline:
                    self.lease.close()
                    raise ValueError(
                        'Another shell already owns the wallpaper runtime.'
                    ) from error
                time.sleep(0.1)
        self.token = None
        self.paused = False
        self.suspended = {}
        self.daemon = None
        self.video = video_wallpaper.Player()
        self.closing = threading.Event()
        self.lifecycle = threading.RLock()
        self.started_at = 0
        self.transient_since = None
        self.restarts = 0
        self.restart_at = 0
        self.failed_selection = None
        self.failure_message = ''
        self.selection = ''
        self.owner = uuid.uuid4().hex
        self.ownership_file = config_dir() / '.engine-ownership.json'
        try:
            try:
                previous = json.loads(self.ownership_file.read_text())
            except FileNotFoundError:
                previous = None
            previous_owner = (
                previous.get('owner') if isinstance(previous, dict) else None
            )
            if previous is not None:
                if not isinstance(previous_owner, str) or not re.fullmatch(
                    r'[0-9a-f]{32}', previous_owner
                ):
                    raise ValueError(
                        'Invalid wallpaper ownership record. Check the runtime directory.'
                    )
                reap_owned(previous_owner)
            restore_native_playback_policy()
            # Journal before Popen: no crash window can lose the inherited marker.
            atomic_write(self.ownership_file, json.dumps({'owner': self.owner}) + '\n')
            previous_state, setting = read_state(), read_setting()
            if (
                setting.get('mode') in {'wallpaper_engine', 'video'}
                and setting.get('selection')
                and previous_state.get('selection') == setting['selection']
                and previous_state.get('status') == 'error'
            ):
                # A shell reload must not reset a terminal failure for the same
                # selection. Only an explicit Apply supplies a new selection.
                self.selection = self.failed_selection = setting['selection']
                self.failure_message = (
                    previous_state.get('error') or 'Wallpaper Engine stopped.'
                )
                self.publish('error', error=self.failure_message)
            else:
                self.publish('idle')
        except Exception:
            self.lease.close()
            raise

    def publish(self, status, **values):
        atomic_write(
            state_file(),
            json.dumps(
                dict(
                    pid=os.getpid(),
                    identity=process_identity(os.getpid()),
                    selection=self.selection,
                    status=status,
                    **values,
                )
            )
            + '\n',
        )

    def start(self):
        if self.closing.is_set():
            raise ValueError('Wallpaper runtime is shutting down.')
        if existing_engine():
            raise ValueError(
                'A separate Wallpaper Engine session is already running. Close it before using this provider.'
            )
        status = installation_status({'installed': True})
        if not status['ready']:
            raise ValueError(status['message'])
        executable = shutil.which('wallpiperd')
        if not executable or not shutil.which('wallpiperctl'):
            raise ValueError('Install Wallpiper to use Wallpaper Engine.')
        environment = dict(
            os.environ, WALLPIPER_PORTAL='hyprland', WALLPIPER_TRAY_OPTS='notray'
        )
        # Tiled exports can import successfully yet display as stripes on
        # Hyprland/Mesa. Linear dma-bufs retain the GPU copy/capture path.
        environment.setdefault('WALLPIPER_FORCE_LINEAR', '1')
        renderer = engine_executable()
        if not renderer:
            raise ValueError(
                'Wallpaper Engine is not installed or could not be found. Install Wallpaper Engine in Steam, then apply again.'
            )
        if not os.environ.get('WALLPIPER_WE_EXE'):
            # Wallpiper prepares a fresh Steam installation by copying its
            # distribution files beside assets/projects before launching it.
            # Starting inside distribution cannot find those application assets.
            if renderer.parent.name == 'distribution':
                renderer = renderer.parent.parent / renderer.name
            for steam_root in library_paths():
                if renderer.is_relative_to(steam_root / 'steamapps/common'):
                    environment['WALLPIPER_STEAM_ROOT'] = str(steam_root)
                    break
        environment['WALLPIPER_WE_EXE'] = str(renderer)
        install_native_playback_policy(renderer)
        self.renderer = renderer
        self.dumps = crash_dumps(renderer)
        proton = proton_executable()
        if proton:
            environment['WALLPIPER_PROTON_BIN'] = str(proton)
        environment['DESKTOP_WALLPAPER_OWNER'] = self.owner
        # Isolate daemon sockets and tracked PIDs from manually started sessions.
        environment['WALLPIPER_TEMP_DIR'] = str(state_file().parent / 'wallpiper')
        self.environment = environment
        log_path = state_file().parent / 'daemon.log'
        if log_path.exists():
            log_path.replace(log_path.with_name('daemon.previous.log'))
        self.log = log_path.open('w')
        try:
            atomic_write(self.ownership_file, json.dumps({'owner': self.owner}) + '\n')
            self.daemon = subprocess.Popen(
                [executable],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=self.log,
                stderr=self.log,
                start_new_session=True,
                preexec_fn=die_with_worker,
            )
        except OSError:
            self.log.close()
            raise
        self.started_at = time.monotonic()
        if self.closing.is_set():
            self.stop()

    def stop(self):
        self.video.stop()
        self.resume_renderer()
        if self.daemon:
            if self.daemon.poll() is None:
                # Wallpiper's SIGTERM handler detaches the display and cleans up
                # its renderer and portal, including their separate process groups.
                self.daemon.terminate()
                try:
                    self.daemon.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    self.daemon.kill()
                    self.daemon.wait(timeout=3)
            self.daemon = None
            self.log.close()
        reap_owned(self.owner)
        restore_native_playback_policy()
        self.token = None
        self.paused = False
        self.transient_since = None

    def resume_renderer(self):
        for pid, identity in self.suspended.items():
            if identity and process_identity(pid) == identity:
                try:
                    os.kill(pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
        self.suspended = {}

    def renderers(self, owned):
        """The daemon's tracked renderer processes that still carry our marker."""
        try:
            tracked = (
                Path(self.environment['WALLPIPER_TEMP_DIR']) / 'wallpiper-renderer-pid'
            )
            pids = {int(value) for value in tracked.read_text().split()}
        except (OSError, ValueError):
            return {}
        return {pid: owned[pid] for pid in pids if pid in owned}

    def pause_renderer(self, paused, renderers):
        if not paused:
            self.resume_renderer()
        control('pause' if paused else 'play', environment=self.environment)
        if paused:
            for pid, identity in renderers.items():
                if process_identity(pid) == identity:
                    os.kill(pid, signal.SIGSTOP)
                    self.suspended[pid] = identity
        self.paused = paused

    def close(self):
        self.closing.set()
        with self.lifecycle:
            if self.lease.closed:
                return
            self.stop()
            if self.failed_selection != self.selection:
                self.publish('idle')
            self.ownership_file.unlink(missing_ok=True)
            self.lease.close()

    def sync(self, request):
        with self.lifecycle, control_lock():
            if self.closing.is_set():
                return {'screens': []}
            setting = read_setting()
            if setting.get('mode') not in {'wallpaper_engine', 'video'}:
                self.stop()
                # A QML unload can immediately kill the worker. Clear the
                # journal before acknowledging that all owned children are gone.
                self.ownership_file.unlink(missing_ok=True)
                self.publish('idle')
                return {'screens': []}
            selection = setting.get('selection', '')
            if selection != self.selection:
                self.restarts = 0
                self.restart_at = 0
                self.transient_since = None
            self.selection = selection
            if self.failed_selection == self.selection:
                return {'screens': [], 'error': self.failure_message}
            try:
                if (
                    not isinstance(selection, str)
                    or not selection
                    or (
                        setting.get('mode') == 'wallpaper_engine'
                        and not WORKSHOP_ID.fullmatch(
                            str(setting.get('workshop_id', ''))
                        )
                    )
                ):
                    raise ValueError(
                        'Invalid saved Wallpaper Engine selection. Apply an installed wallpaper again.'
                    )
                if time.monotonic() < self.restart_at:
                    return {'screens': [], 'recovering': True}
                if setting.get('mode') == 'video':
                    return self.video.sync(self, request, setting)
                self.video.stop()
                result = self.sync_engine(request, setting)
                self.transient_since = None
                return result
            except TransientError as error:
                now = time.monotonic()
                if self.transient_since is None:
                    self.transient_since = now
                if now - self.transient_since < RECOVERY_TIMEOUT:
                    self.publish('recovering', error=str(error))
                    return {'screens': [], 'recovering': True}
                return self.restart(error)
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                return self.fail(error)

    def fail(self, error):
        self.stop()
        self.failed_selection = self.selection
        message = (
            str(error)
            + (
                ' Check video.log in '
                if read_setting().get('mode') == 'video'
                else ' Check daemon.log and daemon.previous.log in '
            )
            + str(state_file().parent)
            + '.'
            + ' Apply wallpaper to retry, or choose a still image.'
        )
        self.failure_message = message
        self.publish('error', error=message)
        return {'screens': [], 'error': message}

    def restart(self, error):
        self.stop()
        if self.restarts >= MAX_RESTARTS:
            return self.fail(error)
        self.restart_at = time.monotonic() + 2**self.restarts
        self.restarts += 1
        self.publish('recovering', error=str(error), restarts=self.restarts)
        return {'screens': [], 'recovering': True}

    def check_crash(self):
        if not self.daemon:
            return
        current = crash_dumps(self.renderer)
        fresh = [
            path
            for path, identity in current.items()
            if self.dumps.get(path) != identity
        ]
        if fresh:
            dump = sorted(fresh)[-1]
            # The crash handler creates the file before writing the minidump.
            # Give it a bounded chance to write diagnostic data before teardown.
            deadline = time.monotonic() + 2
            while (
                any(current[path][2] == 0 for path in fresh)
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
                current = crash_dumps(self.renderer)
                fresh = [path for path in fresh if path in current]
            raise ValueError(
                'Wallpaper Engine crashed. Automatic retries stopped to avoid repeated crash dialogs.'
                + ' Crash dump: '
                + dump
                + '.'
            )

    def sync_engine(self, request, setting):
        monitors = request.get('monitors', [])
        clients = request.get('clients', [])
        if not any(
            not monitor.get('disabled') and monitor.get('dpmsStatus') is not False
            for monitor in monitors
        ):
            # Hyprland owns sleep detection; Wine's hidden windows cannot tell
            # whether a physical output is awake. Suspend existing rendering
            # while all outputs sleep, without starting one or consuming retries.
            if (
                self.daemon
                and self.daemon.poll() is None
                and self.token
                and not self.paused
            ):
                self.pause_renderer(True, self.renderers(owned_processes(self.owner)))
            self.started_at = time.monotonic()
            self.publish('waiting')
            return {'screens': []}
        if self.daemon is None:
            self.start()
            self.publish('starting')
        if self.daemon is None:
            return {'screens': []}
        self.check_crash()
        if self.daemon.poll() is not None:
            return self.restart(
                ValueError(
                    'Wallpaper Engine stopped. Check the Wallpiper installation and apply again.'
                )
            )
        owned = owned_processes(self.owner)
        dismiss_owned_picker(owned)
        renderers = self.renderers(owned)
        if not renderers:
            # A -control launch before the daemon's renderer exists can make
            # Wallpiper mistake that short-lived process for the renderer and
            # skip launching it. Wait for the daemon's own tracked process.
            if self.token:
                return self.restart(ValueError("Wallpaper Engine's renderer stopped."))
            if time.monotonic() - self.started_at > STARTUP_TIMEOUT:
                raise ValueError(
                    "Wallpaper Engine's renderer did not start. Check the Wallpiper renderer log and Proton installation, then apply again."
                )
            return {'screens': []}
        identifier = str(setting.get('workshop_id', ''))
        surfaces = portal_surfaces(hypr_query('layers'), visible_only=False)
        screens = [
            monitor['name']
            for monitor in monitors
            if not monitor.get('disabled') and monitor.get('name') in surfaces
        ]
        if not screens:
            if self.token:
                raise TransientError(
                    "Wallpaper Engine's desktop surfaces are temporarily unavailable."
                )
            if time.monotonic() - self.started_at > STARTUP_TIMEOUT:
                raise ValueError(
                    "Wallpaper Engine's desktop surfaces did not become available."
                )
            return {'screens': []}
        # Portal surface addresses can change during output setup or wake. That
        # does not change the project and must not reload its media sources.
        token = (
            self.selection,
            identifier,
            len([m for m in monitors if not m.get('disabled')]),
        )
        fullscreen = visible_fullscreen(monitors, clients)
        if token != self.token:
            # Commands and daemon must share the inherited Steam/Proton
            # settings. The private temp directory is used for daemon IPC.
            try:
                self.resume_renderer()
                control('mute', environment=self.environment)
                visible_before_apply = portal_surfaces(hypr_query('layers'))
                preview = apply_project(
                    identifier,
                    token[2],
                    self.environment,
                    restored=self.token is None
                    and all(
                        m.get('name') in visible_before_apply
                        for m in monitors
                        if not m.get('disabled')
                    ),
                )
                control('play', environment=self.environment)
                control('mute', environment=self.environment)
            except TransientError:
                self.check_crash()
                if (
                    self.token is None
                    and time.monotonic() - self.started_at < STARTUP_TIMEOUT
                ):
                    return {'screens': []}
                raise
            self.check_crash()
            self.token = token
            self.paused = False
            if preview:
                update_lock_background(preview, config_dir().parent)
                if setting.get('image') != preview.as_uri():
                    setting['image'] = preview.as_uri()
                    atomic_write(
                        config_dir() / 'wallpaper.json', json.dumps(setting) + '\n'
                    )
        # A newly created portal is transparent until the renderer supplies
        # frames. Its existence alone must not hide the still-image fallback
        # or report that Apply succeeded.
        visible = portal_surfaces(hypr_query('layers'))
        screens = [screen for screen in screens if screen in visible]
        if not screens:
            if time.monotonic() - self.started_at > STARTUP_TIMEOUT:
                raise TransientError(
                    "Wallpaper Engine's visible frames are temporarily unavailable."
                )
            return {'screens': []}
        if fullscreen != self.paused:
            self.pause_renderer(fullscreen, renderers)
        if time.monotonic() - self.started_at > HEALTHY_SECONDS:
            # Occasional hotplug/wake recoveries over a long session must not
            # exhaust the budget meant for a daemon that cannot stay up.
            self.restarts = 0
        self.publish('ready', screens=screens, paused=self.paused)
        return {'screens': screens, 'paused': self.paused}


if __name__ == '__main__':
    from spaces.movies.worker import serve

    runtime = Runtime()

    def sync(request):
        if 'monitors' not in request:
            request['monitors'] = hypr_query('monitors')
        if 'clients' not in request:
            request['clients'] = hypr_query('clients')
        return runtime.sync(request)

    def shutdown(signum, frame):
        runtime.close()
        os._exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        serve(sync, controls=('sync',))
    finally:
        runtime.close()
