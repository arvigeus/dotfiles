"""Allowlisted, recoverable storage cleanup. Never accepts paths or shell commands."""

from contextlib import contextmanager
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time


def run(*args, accept=(0,)):
    result = subprocess.run(
        args,
        cwd=Path.home(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode not in accept:
        raise RuntimeError(
            (result.stderr.strip() or result.stdout.strip() or f'{args[0]} failed.')[
                -1200:
            ]
        )
    return result.stdout.strip()


def location(name, fallback):
    return Path(os.path.abspath(Path(os.environ.get(name) or fallback).expanduser()))


def repository():
    return next(
        (
            parent
            for parent in Path(__file__).resolve().parents
            if (parent / 'generate-config.py').is_file() and (parent / '.git').exists()
        ),
        None,
    )


def catalog():
    home = Path.home()
    cache = location('XDG_CACHE_HOME', home / '.local/cache')
    data = location('XDG_DATA_HOME', home / '.local/share')
    cargo = location('CARGO_HOME', data / 'cargo')
    state = location('XDG_STATE_HOME', home / '.local/state')
    private_state = location('DOTFILES_PRIVATE_STATE_DIR', state / 'dotfiles-private')
    agent_state = location('SYSTEM_AGENT_STATE', state / 'system-agent')
    agent_cache = location('SYSTEM_AGENT_CACHE', cache / 'system-agent')
    agent_data = location('SYSTEM_AGENT_DATA', data / 'system-agent')
    # Each path has one owner. No blanket XDG cache or app-profile deletion.
    entries = [
        dict(
            id='pacman',
            admin=True,
            title='System packages',
            detail='Removes offline rollback copies.',
            command=['pkexec', '/usr/bin/paccache', '--remove', '--keep', '0'],
            requires=['pkexec', 'paccache'],
        ),
        dict(
            id='paru',
            title='AUR packages',
            detail='Archives only; keeps source edits.',
            paths=[cache / 'paru'],
            archives=True,
        ),
        dict(
            id='mise-cache',
            title='Mise cache',
            detail='Keeps installed tools.',
            command=['mise', 'cache', 'clear'],
        ),
        dict(
            id='npm',
            title='npm cache',
            detail='Downloaded packages.',
            command=['npm', 'cache', 'clean', '--force'],
        ),
        dict(
            id='pnpm',
            title='pnpm store',
            detail='Unused packages only.',
            command=['pnpm', 'store', 'prune'],
        ),
        dict(
            id='bun',
            title='Bun cache',
            detail='Downloaded packages.',
            command=['bun', 'pm', 'cache', 'rm'],
        ),
        dict(
            id='pip',
            title='pip cache',
            detail='Downloaded packages & wheels.',
            command=['pip', 'cache', 'purge'],
        ),
        dict(
            id='uv',
            title='uv cache',
            detail='Keeps environments.',
            command=['uv', 'cache', 'clean'],
        ),
        dict(
            id='cargo',
            title='Cargo cache',
            detail='Crate archives only.',
            paths=[cargo / 'registry/cache'],
        ),
        dict(
            id='browser',
            title='Browser cache',
            detail='Close browsers first.',
            paths=[
                cache / 'google-chrome',
                cache / 'chromium',
                cache / 'mozilla',
                home / '.var/app/com.google.Chrome/cache/google-chrome',
                home / '.var/app/org.chromium.Chromium/cache/chromium',
                home / '.var/app/org.mozilla.firefox/cache/mozilla',
            ],
        ),
        dict(
            id='thumbnails',
            title='Thumbnails & shaders',
            detail='Previews & shaders rebuild as needed.',
            paths=[
                cache / 'thumbnails',
                cache / 'mesa_shader_cache',
                cache / 'mesa_shader_cache_db',
                cache / 'mesa_shader_cache_sf',
                cache / 'nvidia/GLCache',
            ],
        ),
        dict(
            id='podman',
            title='Podman images',
            detail='Unused registry images only.',
            command=['podman'],
            special='podman',
        ),
        dict(
            id='flatpak-user',
            title='Flatpak runtimes · user',
            detail='Unused runtimes only.',
            command=['flatpak', 'uninstall', '--user', '--unused', '--noninteractive'],
        ),
        dict(
            id='flatpak-system',
            admin=True,
            title='Flatpak runtimes · system',
            detail='Unused runtimes only.',
            command=[
                'flatpak',
                'uninstall',
                '--system',
                '--unused',
                '--noninteractive',
            ],
        ),
        dict(
            id='mise-unused',
            title='Unused Mise versions',
            detail='One-off versions may need reinstalling.',
            command=['mise', 'prune', '--tools', '--yes'],
            group='Installed tools',
        ),
        dict(
            id='mise-tools',
            title='All Mise tools',
            detail='Run mise install to restore tools.',
            command=['mise', 'uninstall', '--all', '--yes'],
            group='Installed tools',
        ),
    ]
    maintenance = [
        dict(
            id='dotfiles-backups',
            title='Old configuration backups',
            detail='Keeps the last 30 days and the newest backup.',
            admin=True,
            group='Configuration & maintenance',
            command=['pkexec', '/usr/local/libexec/dotfiles-backup-cleanup'],
            requires=['pkexec', '/usr/local/libexec/dotfiles-backup-cleanup'],
        )
    ]
    if repository():
        maintenance.append(
            dict(
                id='dotfiles-development',
                title='Dotfiles development caches',
                detail='Python and lint caches; keeps source and settings.',
                group='Configuration & maintenance',
                special='development',
                requires=['git'],
                repo=repository(),
            )
        )
    maintenance.extend(
        [
            dict(
                id='private-backups',
                title='Old private configuration backups',
                detail='Keeps the last 30 days and the newest backup.',
                group='Configuration & maintenance',
                paths=[private_state / 'backups'],
                state=private_state,
                special='private-backups',
            ),
            dict(
                id='agent-history',
                title='Maintenance agent history',
                detail='Keeps newest results, referenced evidence and pending reviews.',
                group='Configuration & maintenance',
                paths=[agent_state / 'runs', agent_state / 'updates'],
                state=agent_state,
                data=agent_data,
                special='agent-history',
            ),
            dict(
                id='agent-cache',
                title='Maintenance agent downloads',
                detail='Upstream documents rebuild as needed; keeps knowledge and proposals.',
                group='Configuration & maintenance',
                paths=[agent_cache],
                state=agent_state,
                cache=agent_cache,
                special='agent-cache',
            ),
        ]
    )
    private_repo = home / 'Projects/dotfiles-private'
    if (private_repo / '.git').exists():
        maintenance.append(
            dict(
                id='private-development',
                title='Private dotfiles development caches',
                detail='Python and lint caches; keeps saved configuration.',
                group='Configuration & maintenance',
                special='development',
                requires=['git'],
                repo=private_repo,
                private=True,
            )
        )
    index = next(
        index
        for index, row in enumerate(entries)
        if row.get('group') == 'Installed tools'
    )
    return entries[:index] + maintenance + entries[index:]


def development_cache(root=None, private=False):
    root = root or repository()
    if root is None:
        raise ValueError('The source checkout is unavailable.')
    paths = run(
        'git',
        '-C',
        str(root),
        'ls-files',
        '--others',
        '--ignored',
        '--exclude-standard',
        '--directory',
        '-z',
    )
    for name in paths.split('\0'):
        path = Path(name.rstrip('/'))
        # Only ignored cache directories; never tracked assets or all ignored files.
        if (
            name.endswith('/')
            and path.name in ('__pycache__', '.ruff_cache', '.pytest_cache')
            and not path.is_absolute()
            and '..' not in path.parts
            and '.git' not in path.parts
            and (not private or not set(path.parts) & {'files', 'symlinks'})
        ):
            clear_path(root / path)


def present(path):
    # Use the same no-follow walk as removal, so a redirected location is never offered.
    try:
        os.close(open_directory(path))
    except OSError:
        return False
    return True


def inventory():
    rows = []
    for entry in catalog():
        needed = entry.get('requires', entry.get('command', [])[:1])
        available = (
            all(shutil.which(tool) for tool in needed)
            if needed
            else any(present(p) for p in entry['paths'])
        )
        rows.append(
            {key: entry[key] for key in ('id', 'title', 'detail')}
            | dict(
                group=entry.get('group', 'Caches and downloads'),
                available=bool(available),
                admin=entry.get('admin', False),
            )
        )
    return rows


DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def open_directory(path):
    # Open every component without following symlinks; callers then work by fd.
    # A redirected cache must never turn into a traversal of personal files.
    fd = os.open('/', DIRECTORY)
    try:
        for part in Path(path).absolute().parts[1:]:
            child = os.open(part, DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def refuse_personal_root(path):
    path = Path(os.path.abspath(path))
    roots = [Path.home()] + [
        location(key, Path.home() / fallback)
        for key, fallback in (
            ('XDG_CONFIG_HOME', '.config'),
            ('XDG_DATA_HOME', '.local/share'),
            ('XDG_STATE_HOME', '.local/state'),
            ('XDG_CACHE_HOME', '.local/cache'),
        )
    ]
    if path == Path('/') or any(path == root or path in root.parents for root in roots):
        raise ValueError('Refusing to remove a home, configuration or data directory.')
    return path


@contextmanager
def operation(folder, name):
    fd = open_directory(refuse_personal_root(folder))
    try:
        lock = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(lock)
    finally:
        os.close(fd)


def private_backups(state, *, now=None):
    with operation(state, 'operation.lock'):
        fd = open_directory(state / 'backups')
        try:
            rows = []
            for name in os.listdir(fd):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if re.fullmatch('[a-f0-9]{32}', name) and (
                    stat.S_ISREG(info.st_mode)
                    or stat.S_ISDIR(info.st_mode)
                    or stat.S_ISLNK(info.st_mode)
                ):
                    rows.append(
                        (max(info.st_mtime_ns, info.st_ctime_ns), name, info.st_ino)
                    )
            newest = max(rows, default=None)
            selected = []
            cutoff = (time.time() if now is None else now) - 30 * 86400
            for age, name, inode in rows:
                if (age, name, inode) == newest or age / 1e9 >= cutoff:
                    continue
                current = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if (
                    current.st_ino != inode
                    or max(current.st_mtime_ns, current.st_ctime_ns) != age
                ):
                    raise RuntimeError('Backup changed during cleanup.')
                selected.append(name)
            clear_directory(fd, only=selected)
            return len(selected)
        finally:
            os.close(fd)


def read_json(path, default):
    if path.is_symlink() or (path.exists() and path.stat().st_size > 2 * 1024 * 1024):
        raise ValueError('Invalid maintenance metadata; preserve evidence for review.')
    return json.loads(path.read_text()) if path.exists() else default


def agent_references(state, data):
    chunks = [json.dumps(read_json(state / 'updates.json', []))]
    for folder in (data / 'knowledge', data / 'proposals'):
        for path in folder.rglob('*'):
            if (
                path.is_file()
                and not path.is_symlink()
                and path.suffix in ('.md', '.json', '.py', '.patch', '.diff')
            ):
                if path.stat().st_size > 512 * 1024:
                    raise ValueError(
                        'Oversized maintenance metadata; preserve evidence for review.'
                    )
                chunks.append(path.read_text())
    for name in ('findings.json', 'last-report.json', 'last-report.md'):
        path = data / name
        if path.is_file():
            if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError(
                    'Invalid maintenance metadata; preserve evidence for review.'
                )
            chunks.append(path.read_text())
    if sum(map(len, chunks)) > 8 * 1024 * 1024:
        raise ValueError(
            'Oversized maintenance metadata; preserve evidence for review.'
        )
    return '\n'.join(chunks)


def agent_history(state, data):
    with operation(state, 'agent.lock'):
        refs = agent_references(state, data)
        count = 0
        for kind in ('runs', 'updates'):
            root = state / kind
            try:
                fd = open_directory(root)
            except FileNotFoundError:
                continue
            try:
                candidates, newest, statuses = [], set(), set()
                for name in sorted(os.listdir(fd), reverse=True):
                    if not re.fullmatch(
                        r'[0-9]{8}T[0-9]{6}\.[0-9]{6}Z', name
                    ) or not stat.S_ISDIR(
                        os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode
                    ):
                        continue
                    if kind == 'runs':
                        status = read_json(root / name / 'run.json', {}).get('status')
                        if status not in ('complete', 'failed'):
                            continue
                        if status not in statuses:
                            newest.add(name)
                            statuses.add(status)
                    elif not newest:
                        newest.add(name)
                    candidates.append(name)
                # Any mention of kind/timestamp pins the evidence, whether it is
                # written as an absolute, relative or ~ path.
                selected = [
                    name
                    for name in candidates
                    if name not in newest and f'{kind}/{name}' not in refs
                ]
                clear_directory(fd, only=selected)
                count += len(selected)
            finally:
                os.close(fd)
        return count


def agent_cache(state, cache):
    with operation(state, 'agent.lock'), operation(cache, 'http.lock'):
        fd = open_directory(cache)
        try:
            names = [
                name
                for name in os.listdir(fd)
                if name in ('notes-http.json', 'feeds-http.json')
                or re.fullmatch(r'tool-[A-Za-z0-9_-]+', name)
            ]
            clear_directory(fd, only=names)
            return len(names)
        finally:
            os.close(fd)


def clear_path(path, archives=False):
    try:
        fd = open_directory(refuse_personal_root(path))
    except FileNotFoundError:
        return
    try:
        if archives:
            clear_archives(fd)
        else:
            clear_directory(fd)
    finally:
        os.close(fd)


ARCHIVE = re.compile(r'.+\.pkg\.tar\.(?:zst|xz|gz|bz2)(?:\.sig)?')


def clear_archives(fd):
    # makepkg writes packages beside the PKGBUILD in paru's clone/<pkgbase>/.
    # Sources, edits and the src/ and pkg/ build trees (pkg/ is mode 0111) stay.
    try:
        clone = os.open('clone', DIRECTORY, dir_fd=fd)
    except FileNotFoundError:
        return
    try:
        for base in os.listdir(clone):
            try:
                build = os.open(base, DIRECTORY, dir_fd=clone)
            except OSError as error:
                if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                    continue
                raise
            try:
                for name in os.listdir(build):
                    if ARCHIVE.fullmatch(name):
                        try:
                            os.unlink(name, dir_fd=build)
                        except (FileNotFoundError, IsADirectoryError):
                            pass
            finally:
                os.close(build)
    finally:
        os.close(clone)


def clear_directory(fd, only=None):
    # shutil's fd-based implementation prevents symlink substitution.
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError('Safe cache removal is unavailable on this platform.')
    for name in os.listdir(fd) if only is None else only:
        try:
            try:
                shutil.rmtree(name, dir_fd=fd)
            except NotADirectoryError:
                os.unlink(name, dir_fd=fd)
            except OSError:
                # rmtree rejects symlinks; unlink only the link itself.
                if stat.S_ISLNK(
                    os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode
                ):
                    os.unlink(name, dir_fd=fd)
                else:
                    raise
        except FileNotFoundError:
            pass


def podman_images():
    """Remove pulled registry images; local builds have no RepoDigests."""
    for image in json.loads(run('podman', 'images', '--format', 'json')):
        identity = image.get('Id', '')
        if image.get('RepoDigests') and re.fullmatch(
            r'(?:sha256:)?[a-f0-9]{64}', identity
        ):
            # Never force: rmi exits 2 for images used by containers or child images.
            run('podman', 'rmi', identity, accept=(0, 1, 2))


def failure_message(error):
    """Keep terminal diagnostics out of desktop notifications."""
    text = str(error).lower()
    if isinstance(error, subprocess.TimeoutExpired):
        return 'Cleanup took too long. Try again.'
    if (
        'operation is already running' in text
        or 'configuration operation' in text
        or 'resource temporarily unavailable' in text
    ):
        return 'Maintenance is running. Try cleanup again later.'
    if any(
        word in text
        for word in (
            'not authorized',
            'not authorised',
            'authentication',
            'authorization',
            'cancelled',
            'canceled',
        )
    ):
        return 'Administrator approval was not granted. Try again and approve the authentication request.'
    if isinstance(error, PermissionError) or 'permission denied' in text:
        return (
            'Some cached files could not be removed because you do not have permission.'
        )
    if isinstance(error, FileNotFoundError):
        return 'The cleanup tool is no longer available. Install it and try again.'
    if isinstance(error, OSError) and error.errno in (errno.ELOOP, errno.ENOTDIR):
        return 'The cache location points elsewhere and was left untouched.'
    if 'refusing to remove' in text:
        return 'The cache location includes personal settings or data and was left untouched.'
    return 'Cleanup could not finish. Try again.'


def clean(selected, emit):
    entries = {row['id']: row for row in catalog()}
    if (
        not isinstance(selected, list)
        or not selected
        or any(not isinstance(key, str) or key not in entries for key in selected)
        or len(selected) != len(set(selected))
    ):
        raise ValueError('Choose valid cleanup categories.')
    if 'mise-tools' in selected and 'mise-unused' in selected:
        selected = [key for key in selected if key != 'mise-unused']
    # Remove runtimes last, even when their checkbox was selected first.
    selected = [key for key in entries if key in selected]
    results = []
    for key in selected:
        entry = entries[key]
        emit(dict(progress=entry['title']))
        try:
            if entry.get('special') == 'podman':
                podman_images()
            elif entry.get('special') == 'development':
                development_cache(entry.get('repo'), entry.get('private', False))
            elif entry.get('special') == 'private-backups':
                private_backups(entry['state'])
            elif entry.get('special') == 'agent-history':
                agent_history(entry['state'], entry['data'])
            elif entry.get('special') == 'agent-cache':
                agent_cache(entry['state'], entry['cache'])
            elif 'command' in entry:
                run(*entry['command'])
            else:
                for path in dict.fromkeys(entry['paths']):
                    clear_path(path, entry.get('archives', False))
            results.append(dict(id=key, title=entry['title'], ok=True))
        except Exception as error:
            results.append(
                dict(
                    id=key, title=entry['title'], ok=False, error=failure_message(error)
                )
            )
    return dict(ok=all(row['ok'] for row in results), results=results)


def main():
    def emit(value):
        print(json.dumps(value), flush=True)

    try:
        request = json.loads(sys.stdin.readline())
        if not isinstance(request, dict):
            raise ValueError('Unknown cleanup operation.')
        if request.get('op') == 'scan':
            emit(dict(ok=True, entries=inventory()))
        elif request.get('op') == 'clean':
            emit(clean(request.get('selected'), emit))
        else:
            raise ValueError('Unknown cleanup operation.')
    except (OSError, ValueError, RuntimeError) as error:
        emit(dict(ok=False, error=failure_message(error)))


if __name__ == '__main__':
    main()
