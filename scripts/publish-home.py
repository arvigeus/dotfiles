#!/usr/bin/env python3
"""Copy staged generated files and install staged links into the user's home."""
import os
from pathlib import Path
import shutil
import sys
import tempfile

staging, home = map(Path, sys.argv[1:3])
uid, gid = map(int, sys.argv[3:5])


def check_parents(target):
    for parent in target.parents:
        if parent == home:
            break
        if parent.is_symlink():
            sys.exit(f'Refusing to write through directory symlink: {parent}')


def mkdir_owned(directory):
    if directory.exists():
        return
    mkdir_owned(directory.parent)
    directory.mkdir()
    os.chown(directory, uid, gid)



sources = sorted(staging.rglob('*'))
# Validate all destinations before publishing anything.
for source in sources:
    target = home / source.relative_to(staging)
    check_parents(target)
    if source.is_dir() and not source.is_symlink():
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            sys.exit(f'Refusing to replace home path with a directory: {target}')
    elif target.is_dir() and not target.is_symlink():
        sys.exit(f'Refusing to replace home directory: {target}')

for source in sources:
    relative = source.relative_to(staging)
    target = home / relative
    if source.is_dir() and not source.is_symlink():
        mkdir_owned(target)
        continue
    mkdir_owned(target.parent)
    fd, name = tempfile.mkstemp(prefix='.tmp-', dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        if source.is_symlink():
            temporary.unlink()
            temporary.symlink_to(os.readlink(source))
            os.lchown(temporary, uid, gid)
        else:
            shutil.copyfile(source, temporary)
            temporary.chmod(source.stat().st_mode & 0o777)
            os.chown(temporary, uid, gid)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)

