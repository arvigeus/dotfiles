#!/usr/bin/env python3
"""Reconcile staged home files, preserving local edits for individual review."""

import argparse
from pathlib import Path

from reconcile import State, publish_tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('staging', type=Path)
    parser.add_argument('home', type=Path)
    parser.add_argument('uid', type=int)
    parser.add_argument('gid', type=int)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    state = State(args.state or args.home / '.local/state/dotfiles')
    if not publish_tree(
        args.staging, args.home, args.uid, args.gid, state, 'home', args.force
    ):
        parser.exit(
            2, 'Local home file conflicts remain; resolve them and run apply again.\n'
        )


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
