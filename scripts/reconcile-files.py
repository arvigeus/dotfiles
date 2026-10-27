#!/usr/bin/env python3
"""Reconcile declared system assets or a tree of generated files."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from reconcile import Files, State, publish_tree


def system_assets(config, repo, staging):
    entries = []
    for kind in ('files', 'symlinks'):
        for entry in config['extra'][kind]:
            if entry['target'].startswith('home/'):
                continue
            source = repo / entry['source']
            target = Path(entry['target'])
            if (
                not target.is_absolute()
                or '..' in target.parts
                or target == Path('/')
                or not source.is_file()
                or not source.resolve().is_relative_to(repo.resolve())
            ):
                raise ValueError(f'Invalid asset: {entry}')
            prepared = staging / str(len(entries))
            if kind == 'files':
                shutil.copy2(source, prepared)
                prepared.chmod(int(entry['mode'], 8))
            else:
                prepared.symlink_to(source)
            entries.append((prepared, target, 0, 0))
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    assets = sub.add_parser('assets')
    assets.add_argument('config', type=Path)
    assets.add_argument('repo', type=Path)
    tree = sub.add_parser('tree')
    tree.add_argument('staging', type=Path)
    tree.add_argument('destination', type=Path)
    tree.add_argument('uid', type=int)
    tree.add_argument('gid', type=int)
    tree.add_argument('scope')
    for command in (assets, tree):
        command.add_argument('state', type=Path)
        command.add_argument(
            '--force',
            action='store_true',
            help='Initial installation only: replace existing defaults',
        )
        command.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    state = State(args.state, dry_run=args.dry_run)
    if args.action == 'tree':
        complete = publish_tree(
            args.staging,
            args.destination,
            args.uid,
            args.gid,
            state,
            args.scope,
            args.force,
        )
    else:
        config = json.loads(args.config.read_text())
        with tempfile.TemporaryDirectory() as directory:
            entries = system_assets(config, args.repo.resolve(), Path(directory))
            complete = Files(state, force=args.force).sync('assets', entries)
    if not complete and not args.dry_run:
        parser.exit(
            2, 'Local file conflicts remain; resolve them and run apply again.\n'
        )


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
