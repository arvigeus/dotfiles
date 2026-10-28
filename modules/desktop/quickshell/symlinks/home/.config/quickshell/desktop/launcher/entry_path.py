"""Run a command with the file of a desktop entry ID appended.

uwsm only resolves IDs matching [A-Za-z0-9_][A-Za-z0-9_.-]*, but parses any
entry given by path. Quickshell also lists entries such as "Portal 2" (Steam) or
"wine-Programs-Notepad++-Notepad++". Map the ID back to the file that wins XDG
precedence, as Quickshell's scan did, and leave parsing to the command.
"""

import os
import sys


def entry_path(entry_id):
    home = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    dirs = os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share'
    for data in [home, *dirs.split(':')]:
        if not os.path.isabs(data):
            continue
        root = os.path.join(data, 'applications')
        for directory, _, names in os.walk(root, followlinks=True):
            for name in names:
                path = os.path.join(directory, name)
                relative = os.path.relpath(path, root)
                if relative.replace(os.sep, '-') == entry_id + '.desktop':
                    return path
    return None


def main():
    entry_id, *command = sys.argv[1:]
    path = entry_path(entry_id)
    if not path:
        sys.exit(f'Desktop entry not found: {entry_id}')
    os.execvp(command[0], [*command, path])


if __name__ == '__main__':
    main()
