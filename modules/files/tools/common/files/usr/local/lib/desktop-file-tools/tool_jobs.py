"""Worker utilities shared by the desktop file tools; no shell command evaluation."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile

CURRENT = None


class Cancelled(Exception): pass


def emit(kind, **data):
    print(json.dumps(dict(type=kind, **data)), flush=True)


def row(path, status, detail='', **extra):
    emit('row', path=str(path), status=status, detail=str(detail), **extra)


def cancel(_signum, _frame):
    if CURRENT is not None:
        try: os.killpg(CURRENT.pid, signal.SIGTERM)
        except ProcessLookupError: pass
    raise Cancelled()


def command(argv, *, accepted=(0,), stdin_file=None):
    global CURRENT
    handle = open(stdin_file, 'rb') if stdin_file else subprocess.DEVNULL
    try:
        CURRENT = subprocess.Popen([str(value) for value in argv], stdin=handle,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            env=dict(os.environ, LC_ALL='C'))
        stdout, stderr = CURRENT.communicate()
        if CURRENT.returncode not in accepted:
            diagnostic = stderr.decode(errors='replace').strip()[-8000:]
            raise ValueError(diagnostic or f'{argv[0]} exited with status {CURRENT.returncode}.')
        return stdout
    finally:
        if CURRENT is not None and CURRENT.poll() is None:
            try:
                os.killpg(CURRENT.pid, signal.SIGTERM); CURRENT.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(CURRENT.pid, signal.SIGKILL); CURRENT.communicate()
            except ProcessLookupError: pass
        CURRENT = None
        if stdin_file: handle.close()


def identity(path):
    stat = Path(path).lstat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_mode]


def rename_noreplace(source, target):
    # Linux renameat2 also protects directory publication and rename previews from races.
    function = ctypes.CDLL(None, use_errno=True).renameat2
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if function(-100, os.fsencode(source), -100, os.fsencode(target), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


class Output:
    def __init__(self, target, directory=False):
        self.target = Path(target); self.directory = directory
        if os.path.lexists(self.target): raise FileExistsError(f'Output already exists: {self.target}')
        if not self.target.parent.is_dir(): raise ValueError('Choose an existing output folder.')
        self.temporary = None

    def __enter__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='.file-tools-', dir=self.target.parent)
        self.path = Path(self.temporary.name) / ('output' if self.directory else 'output'+self.target.suffix)
        if self.directory: self.path.mkdir(mode=0o700)
        return self

    def publish(self, detail=''):
        if self.directory:
            rename_noreplace(self.path, self.target)
        else:
            self.path.chmod(0o600)
            os.link(self.path, self.target)
        row(self.target, 'Saved', detail)

    def __exit__(self, *_error):
        if self.temporary: self.temporary.cleanup()


def target_for(path, suffix, extension=None, folder=''):
    path = Path(path)
    return (Path(folder) if folder else path.parent) / (path.stem + ' [' + suffix + ']' + (extension or path.suffix))


def walk(paths):
    seen = set(); count = 0
    for value in paths:
        root = Path(value).absolute()
        entries = [root]
        if root.is_dir() and not root.is_symlink():
            for folder, directories, files in os.walk(root, followlinks=False):
                directories.sort(); files.sort()
                entries.extend(Path(folder) / name for name in [*directories, *files])
                count += len(directories) + len(files)
                if count > 200_000: raise ValueError('The selection exceeds 200,000 entries; choose a smaller folder.')
        for path in entries:
            if path not in seen:
                seen.add(path); yield path


def files(paths, extensions=None):
    return [path for path in walk(paths) if path.is_file() and not path.is_symlink()
            and (extensions is None or path.suffix.lower() in extensions)]


def digest(path, algorithm):
    before = identity(path)
    result = hashlib.new(algorithm)
    with open(path, 'rb') as stream:
        while chunk := stream.read(1024*1024): result.update(chunk)
    if identity(path) != before: raise ValueError(f'File changed while being read: {path}')
    return result.hexdigest()


def batch(paths, function):
    failures = 0
    for index, path in enumerate(paths):
        emit('progress', current=index, total=len(paths), name=Path(path).name)
        try: function(Path(path))
        except (OSError, ValueError, RuntimeError) as error:
            failures += 1; row(path, 'Failed', str(error), error=True)
    emit('progress', current=len(paths), total=len(paths), name='')
    return failures
