"""Resolve the shared or feature-specific browser command without a shell."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


def browser_argv(module, url, config_path=None, command=None):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Browser links must use HTTP or HTTPS.')
    path = (
        Path(config_path)
        if config_path is not None
        else Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        / 'quickshell/desktop/browser.json'
    )
    try:
        config = json.loads(path.read_text())
    except FileNotFoundError:
        config = {}
    if not isinstance(config, dict):
        raise ValueError('browser.json must contain an object.')
    modules = config.get('modules', {})
    if not isinstance(modules, dict):
        raise ValueError('browser.json modules must contain an object.')
    if command is None:
        command = modules.get(module, config.get('command', ['xdg-open']))
    argv = shlex.split(command) if isinstance(command, str) else command
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(part, str) and part for part in argv)
    ):
        raise ValueError('Browser command must be a nonempty string or argument array.')
    return [*argv, url]


def main():
    if len(sys.argv) not in (3, 4):
        raise SystemExit('Usage: browser.py FEATURE URL [COMMAND]')
    try:
        argv = browser_argv(
            sys.argv[1],
            sys.argv[2],
            command=sys.argv[3] if len(sys.argv) == 4 else None,
        )
        os.execvp(argv[0], argv)
    except (OSError, ValueError) as error:
        message = f'Could not open the browser: {error}'
        print(message, file=sys.stderr)
        subprocess.run(
            ['notify-send', '-a', 'Desktop shell', 'Browser launch failed', message],
            check=False,
        )
        raise SystemExit(1) from error


if __name__ == '__main__':
    main()
