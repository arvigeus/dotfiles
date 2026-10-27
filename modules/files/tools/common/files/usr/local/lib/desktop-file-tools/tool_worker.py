"""JSON-lines worker protocol for the native file tools."""

import importlib
import json
from pathlib import Path
import signal
import sys

from tool_jobs import Cancelled, cancel, emit

MODULES = {'pdf': 'pdf_tasks', 'file': 'file_tasks', 'encryption': 'encryption_tasks'}


def main():
    try:
        signal.signal(signal.SIGTERM, cancel)
        request = json.load(sys.stdin)
        module = importlib.import_module(MODULES[request['app']])
        action = request['action']
        paths = [str(Path(value).absolute()) for value in request.get('paths', [])]
        if action == '_pdf_export' and request['app'] == 'pdf':
            import pdf_edits

            options = request['options']
            failures = pdf_edits.export_pdf(
                request['plan'][0],
                options['variant'],
                options['settings'],
                options['directory'],
            )
            emit('done', failures=failures)
            return 0
        if action in ('_edit', '_save') and request['app'] == 'pdf':
            import pdf_edits

            if action == '_edit':
                options = request.get('options', {})
                failures = pdf_edits.stage(
                    options['action'],
                    request['plan'],
                    options['settings'],
                    options['directory'],
                )
            else:
                failures = pdf_edits.save(request['plan'])
            emit('done', failures=failures or 0)
            return 0
        if action not in {item['id'] for item in module.ACTIONS} | (
            {'keys'} if request['app'] == 'encryption' else set()
        ):
            raise ValueError('Unknown operation.')
        failures = (
            module.run(action, paths, request.get('options', {}), request.get('plan'))
            or 0
        )
        emit('done', failures=failures)
    except Cancelled:
        emit('cancelled')
    except Exception as error:
        emit('error', message=str(error))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
