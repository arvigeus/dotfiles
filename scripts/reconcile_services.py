"""Reconcile globally enabled/masked user units declared by the modules."""

import json
from pathlib import Path
import subprocess
import sys

from reconcile import State


def apply_user(extra, state, run=None):
    run = run or (lambda *args: subprocess.run(args, check=True))
    wanted = set(extra.get('user_services', []))
    masked = set(extra.get('masked_user_services', []))
    if wanted & masked:
        raise ValueError(f'User services both enabled and masked: {wanted & masked}')
    old = set(state.data.get('user_services', []))
    for name in sorted(old - wanted):
        run('systemctl', '--global', 'disable', name)
        old.remove(name)
        state.data['user_services'] = sorted(old)
        state.save()
    for name in sorted(set(state.data.get('masked_user_services', [])) - masked):
        run('systemctl', '--global', 'unmask', name)
        state.data['masked_user_services'].remove(name)
        state.save()
    if wanted:
        run('systemctl', '--global', 'enable', *sorted(wanted))
    state.data['user_services'] = sorted(wanted)
    state.save()
    if masked:
        run('systemctl', '--global', 'mask', *sorted(masked))
    state.data['masked_user_services'] = sorted(masked)
    state.save()
    for name in extra.get('disabled_services', []):
        run('systemctl', 'disable', name)


if __name__ == '__main__':
    try:
        apply_user(
            json.loads(Path(sys.argv[1]).read_text())['extra'], State(Path(sys.argv[2]))
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
