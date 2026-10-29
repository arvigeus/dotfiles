"""Content-based reconciliation of the current managed files and service state."""

import difflib
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid


class Review:
    def __init__(self, stream=None):
        self.stream = stream

    def choose(self, message, choices, default):
        stream = self.stream
        input_stream = output_stream = stream
        owned = False
        if stream is None:
            try:
                stream = open('/dev/tty', 'r+')
                input_stream = output_stream = stream
                owned = True
            except OSError:
                if sys.stdin.isatty():
                    input_stream = sys.stdin
                    output_stream = sys.stderr
                else:
                    print(f'{message}: {choices[default]} (no terminal)')
                    return default
        try:
            while True:
                output_stream.write(
                    message
                    + '\n'
                    + ', '.join(f'[{key}] {label}' for key, label in choices.items())
                    + f' [{default}]: '
                )
                output_stream.flush()
                answer = input_stream.readline()
                if not answer:
                    return default
                answer = answer.strip().lower() or default
                if answer in choices:
                    return answer
        finally:
            if owned:
                stream.close()


def fingerprint(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return {'link': os.readlink(path)}
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Expected a regular file or symlink: {path}')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256': digest, 'mode': stat.S_IMODE(info.st_mode)}


def check_parents(path):
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError(f'Refusing to write through directory symlink: {parent}')
        if parent.exists() and not parent.is_dir():
            raise ValueError(f'Not a directory: {parent}')


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def mkdir_owned(path, uid, gid):
    missing = [parent for parent in (path, *path.parents) if not parent.exists()]
    path.mkdir(parents=True, exist_ok=True)
    for parent in missing:
        os.chown(parent, uid, gid)


class State:
    """One current-state manifest, published after each successful change."""

    def __init__(self, directory, dry_run=False):
        self.directory = Path(directory)
        self.path = self.directory / 'state.json'
        self.dry_run = dry_run
        check_parents(self.path)
        if self.path.is_symlink():
            raise ValueError(f'Refusing symlinked state: {self.path}')
        self.data = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {'version': 1, 'files': {}}
        )
        if (
            not isinstance(self.data, dict)
            or self.data.get('version') != 1
            or not isinstance(self.data.get('files'), dict)
        ):
            raise ValueError(f'Invalid reconciliation state: {self.path}')
        for entries in self.data['files'].values():
            if not isinstance(entries, dict):
                raise ValueError(f'Invalid file ownership state: {self.path}')
            for path, record in entries.items():
                if (
                    not Path(path).is_absolute()
                    or Path(path).as_posix() != path
                    or '..' in Path(path).parts
                    or not isinstance(record, dict)
                ):
                    raise ValueError(f'Invalid file ownership state: {self.path}')
                link = set(record) == {'link'} and isinstance(record['link'], str)
                file = (
                    set(record) == {'sha256', 'mode'}
                    and isinstance(record['sha256'], str)
                    and len(record['sha256']) == 64
                    and all(c in '0123456789abcdef' for c in record['sha256'])
                    and type(record['mode']) is int
                    and 0 <= record['mode'] <= 0o7777
                )
                if not (link or file):
                    raise ValueError(f'Invalid file fingerprint: {self.path}')
        for key in (
            'services',
            'user_services',
            'masked_user_services',
            'repositories',
        ):
            if key in self.data and (
                not isinstance(self.data[key], list)
                or not all(isinstance(value, str) and value for value in self.data[key])
            ):
                raise ValueError(f'Invalid {key} state: {self.path}')
        self.saved = json.dumps(self.data, sort_keys=True)

    def save(self):
        encoded = json.dumps(self.data, sort_keys=True)
        if self.dry_run or encoded == self.saved:
            return
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        fd, name = tempfile.mkstemp(prefix='.state-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(json.dumps(self.data, indent=2, sort_keys=True) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            sync_directory(self.directory)
            self.saved = encoded
        finally:
            Path(name).unlink(missing_ok=True)


class Files:
    def __init__(self, state, review=None, force=False):
        self.state = state
        self.review = review or Review()
        self.force = force
        self.backup_id = uuid.uuid4().hex
        self.conflicts = []

    def backup(self, target, current):
        if current is None:
            return
        destination = (
            self.state.directory / 'backups' / self.backup_id / target.relative_to('/')
        )
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(target, destination, follow_symlinks=False)
        if not destination.is_symlink():
            with destination.open('rb') as stream:
                os.fsync(stream.fileno())
        sync_directory(destination.parent)
        if fingerprint(target) != current:
            raise ValueError(
                f'File changed while being backed up; retry apply: {target}'
            )
        print(f'  Backup: {destination}')

    def difference(self, target, source):
        if source is None:
            print(f'Remove {target}: {fingerprint(target)}')
        elif target.is_symlink() or source.is_symlink():
            print(f'{target}: {fingerprint(target)} -> {fingerprint(source)}')
        elif target.stat().st_size > 1024 * 1024 or source.stat().st_size > 1024 * 1024:
            print('File exceeds the 1 MiB diff limit.')
        else:
            try:
                target_text = target.read_text()
                source_text = source.read_text()
            except UnicodeError:
                print('Binary files differ.')
                return
            if self._meld_difference(target, source):
                return
            print(
                ''.join(
                    difflib.unified_diff(
                        target_text.splitlines(True),
                        source_text.splitlines(True),
                        fromfile=str(target),
                        tofile=str(source),
                    )
                ),
                end='',
            )

    @staticmethod
    def _meld_difference(target, source):
        if os.environ.get('DOTFILES_DIFF_EDITOR') != 'meld' or os.geteuid() != 0:
            return False
        username = os.environ.get('SUDO_USER')
        uid_text = os.environ.get('SUDO_UID')
        editor = shutil.which('meld')
        session = {
            name: os.environ[f'DOTFILES_DIFF_{name}']
            for name in (
                'DISPLAY',
                'WAYLAND_DISPLAY',
                'XDG_RUNTIME_DIR',
                'DBUS_SESSION_BUS_ADDRESS',
                'XAUTHORITY',
            )
            if os.environ.get(f'DOTFILES_DIFF_{name}')
        }
        if (
            not username
            or not uid_text
            or not editor
            or not (session.get('WAYLAND_DISPLAY') or session.get('DISPLAY'))
        ):
            return False
        try:
            account = pwd.getpwnam(username)
            if account.pw_uid == 0 or account.pw_uid != int(uid_text):
                return False
            with tempfile.TemporaryDirectory(prefix='dotfiles-diff-') as directory:
                directory = Path(directory)
                current = directory / f'installed-{target.name}'
                configured = directory / f'configured-{source.name}'
                current.write_bytes(target.read_bytes())
                configured.write_bytes(source.read_bytes())
                os.chmod(current, 0o600)
                os.chmod(configured, 0o600)
                os.chown(current, account.pw_uid, account.pw_gid)
                os.chown(configured, account.pw_uid, account.pw_gid)
                os.chown(directory, account.pw_uid, account.pw_gid)
                subprocess.run(
                    [
                        'runuser',
                        '-u',
                        username,
                        '--',
                        'env',
                        *(f'{name}={value}' for name, value in session.items()),
                        editor,
                        str(current),
                        str(configured),
                    ],
                    check=True,
                )
            return True
        except (OSError, subprocess.CalledProcessError, ValueError):
            print('Meld could not be opened; showing the unified diff.')
            return False

    def approved(self, target, source):
        if self.force:
            return True
        if self.state.dry_run:
            return False
        action = 'replace' if source is not None else 'remove'
        while True:
            choice = self.review.choose(
                f'Local changes or untracked file: {target}',
                {'d': 'diff', 'r': action, 'k': 'keep', 'q': 'quit apply'},
                'k',
            )
            if choice == 'd':
                self.difference(target, source)
            elif choice == 'q':
                raise KeyboardInterrupt()
            else:
                return choice == 'r'

    def sync(self, scope, entries):
        """Entries are (source, absolute target, uid, gid); None removes a file."""
        previous = self.state.data['files'].setdefault(scope, {})
        targets = {str(target) for _, target, _, _ in entries}
        if len(targets) != len(entries):
            raise ValueError(f'Duplicate destination in {scope}')
        for source, target, _, _ in entries:
            if not target.is_absolute() or '..' in target.parts:
                raise ValueError(f'Invalid destination: {target}')
            if source is None or fingerprint(source) is None:
                raise ValueError(f'Missing source: {source}')
            for owner, records in self.state.data['files'].items():
                if owner != scope and str(target) in records:
                    raise ValueError(
                        f'Multiple owners for {target}: {owner} and {scope}'
                    )
            check_parents(target)
            fingerprint(target)
        for name in previous:
            if name not in targets:
                check_parents(Path(name))
                fingerprint(Path(name))
        operations = list(entries) + [
            (None, Path(name), 0, 0) for name in sorted(previous) if name not in targets
        ]
        for source, target, uid, gid in operations:
            current = fingerprint(target)
            desired = fingerprint(source) if source is not None else None
            baseline = previous.get(str(target))
            if desired == current:
                if desired is not None:
                    if not self.state.dry_run:
                        info = target.lstat()
                        if (info.st_uid, info.st_gid) != (uid, gid):
                            os.chown(target, uid, gid, follow_symlinks=False)
                    previous[str(target)] = desired
                else:
                    previous.pop(str(target), None)
                self.state.save()
                continue
            clean = current is None or (baseline is not None and current == baseline)
            action = (
                'Remove'
                if desired is None
                else 'Create'
                if current is None
                else 'Update'
            )
            if not clean and not self.approved(target, source):
                print(f'Conflict (kept): {target}')
                self.conflicts.append(str(target))
                continue
            print(f'{action}: {target}')
            if self.state.dry_run:
                continue
            check_parents(target)
            self.backup(target, current)
            if desired is None:
                if fingerprint(target) != current:
                    raise ValueError(f'File changed during apply; retry: {target}')
                target.unlink(missing_ok=True)
                previous.pop(str(target), None)
            else:
                mkdir_owned(target.parent, uid, gid)
                fd, name = tempfile.mkstemp(prefix='.dotfiles-', dir=target.parent)
                os.close(fd)
                temporary = Path(name)
                try:
                    if source.is_symlink():
                        temporary.unlink()
                        temporary.symlink_to(os.readlink(source))
                    else:
                        shutil.copy2(source, temporary)
                        with temporary.open('rb') as stream:
                            os.fsync(stream.fileno())
                    os.chown(temporary, uid, gid, follow_symlinks=False)
                    if fingerprint(temporary) != desired:
                        raise ValueError(
                            f'Source changed during apply; retry: {source}'
                        )
                    if fingerprint(target) != current:
                        raise ValueError(f'File changed during apply; retry: {target}')
                    temporary.replace(target)
                    previous[str(target)] = desired
                finally:
                    temporary.unlink(missing_ok=True)
            sync_directory(target.parent)
            self.state.save()
        return not self.conflicts


def tree_entries(staging, destination, uid, gid):
    return [
        (source, destination / source.relative_to(staging), uid, gid)
        for source in sorted(staging.rglob('*'))
        if source.is_symlink() or source.is_file()
    ]


def publish_tree(staging, destination, uid, gid, state, scope, force=False):
    entries = tree_entries(staging, destination, uid, gid)
    # Generated empty directories (history, XDG folders) have user ownership too.
    directories = [
        destination / source.relative_to(staging)
        for source in sorted(staging.rglob('*'))
        if source.is_dir() and not source.is_symlink()
    ]
    for directory in directories:
        check_parents(directory / '.entry')
    if not state.dry_run:
        for directory in directories:
            mkdir_owned(directory, uid, gid)
    return Files(state, force=force).sync(scope, entries)
