"""On-demand Lemonade control and streaming chat; no conversation storage."""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
import attachments as Files

UNIT = 'lemond.service'
LENGTHS = {
    'brief': 'Keep the answer concise unless the request needs more detail.',
    'balanced': 'Use enough detail to make the answer useful.',
    'detailed': 'Give a thorough, well-structured answer.',
}


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def run(args, timeout=5):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )


def unit_state(user):
    args = [
        'systemctl',
        *(['--user'] if user else []),
        'show',
        UNIT,
        '-p',
        'LoadState',
        '-p',
        'ActiveState',
    ]
    result = run(args)
    return dict(
        line.split('=', 1) for line in result.stdout.splitlines() if '=' in line
    )


def service():
    user, system = unit_state(True), unit_state(False)
    # An already-running system instance owns its models and port. Never start
    # a competing user instance just because the user's unit is inactive.
    if system.get('ActiveState') in ('active', 'activating', 'deactivating'):
        return 'system', system
    return ('user', user) if user.get('LoadState') == 'loaded' else ('', {})


def server_url(scope):
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    path = (
        Path('/var/lib/lemonade/config.json')
        if scope == 'system'
        else config_home / 'lemonade/config.json'
    )
    try:
        config = json.loads(path.read_text())
    except FileNotFoundError:
        config = {}
    port = int(config.get('port', 13305))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid Lemonade port.')
    # The drawer is a local client, even if Lemonade listens on all interfaces.
    return f'http://localhost:{port}'


def request(url, payload=None, timeout=4):
    headers = {'Content-Type': 'application/json'}
    if key := os.environ.get('LEMONADE_API_KEY'):
        headers['Authorization'] = f'Bearer {key}'
    req = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers=headers,
    )

    # Local inference must not go through an HTTP proxy or follow redirects.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    return opener.open(req, timeout=timeout)


def get_json(url):
    with request(url) as response:
        return json.load(response)


def model_aliases(url):
    # Alias metadata only decorates the picker. The public models endpoint and
    # inference remain usable when the administrative endpoint is unavailable.
    try:
        return {
            row['alias']: row['target']
            for row in get_json(url + '/internal/aliases').get('aliases', [])
            if isinstance(row.get('alias'), str) and isinstance(row.get('target'), str)
        }
    except urllib.error.HTTPError as exc:
        exc.close()
        return {}
    except (urllib.error.URLError, OSError, ValueError):
        return {}


def chat_models(data, *, catalogue=False, aliases=None):
    aliases = aliases or {}
    identifiers = {row['id'] for row in data.get('data', []) if row.get('id')}

    def target(identifier):
        # Lemonade resolves aliases for inference. Resolve only their display
        # metadata here, to match concrete download jobs and loaded-model state.
        current, seen = identifier, set()
        while current in aliases and current not in seen:
            seen.add(current)
            current = aliases[current]
        if current not in identifiers and current.startswith(
            ('builtin.', 'user.', 'extra.')
        ):
            bare = current.split('.', 1)[1]
            if bare in identifiers:
                current = bare
        return current

    return sorted(
        [
            dict(
                id=row['id'],
                label=row['id'],
                suggested=bool(row.get('suggested')),
                downloaded=row.get('downloaded') is True,
                size=row.get('size', 0),
                labels=row.get('labels', []),
                alias=row['id'] in aliases,
                target=target(row['id']),
            )
            for row in data.get('data', [])
            if row.get('id')
            and (catalogue or row.get('downloaded') is True)
            and 'chat' in row.get('labels', [])
            and row.get('recipe') != 'cloud'
            and not str(row.get('recipe', '')).startswith('collection.')
        ],
        key=lambda row: (
            not row['downloaded'],
            not row['alias'],
            not row['suggested'],
            row['id'].casefold(),
        ),
    )


def status(known_generation=None, known_aliases=None):
    scope, state = service()
    url = server_url(scope)
    result = dict(
        online=False,
        installed=bool(shutil.which('lemond')),
        scope=scope,
        state=state.get('ActiveState', 'inactive'),
        url=url,
        loaded=[],
        downloads=[],
        error='',
    )
    try:
        health = get_json(url + '/v1/health')
    except urllib.error.HTTPError as exc:
        result.update(
            online=True,
            error=f'Lemonade returned HTTP {exc.code}. Check its API key and settings.',
        )
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        if result['state'] == 'active':
            result['error'] = (
                'Lemonade is running but is not responding. Check its port and service logs.'
            )
        elif result['state'] == 'failed':
            result['error'] = 'Lemonade failed to start. Check its service logs.'
    else:
        result['online'] = True
        result['loaded'] = [
            dict(
                id=row['model_name'],
                busy=bool(row.get('is_busy') or row.get('is_streaming')),
                pinned=bool(row.get('pinned')),
            )
            for row in health.get('all_models_loaded', [])
            if row.get('model_name')
        ]
        try:
            generation = health.get('models_generation')
            aliases = model_aliases(url)
            result['aliases'] = aliases
            if (
                generation is None
                or generation != known_generation
                or aliases != known_aliases
            ):
                result['models'] = chat_models(
                    get_json(url + '/v1/models?show_all=true'),
                    catalogue=True,
                    aliases=aliases,
                )
            result['generation'] = generation
            result['downloads'] = [
                job
                for job in get_json(url + '/v1/downloads')
                if job.get('type') == 'model'
            ]
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            result['error'] = f'Could not refresh Lemonade: {exc}'
    return result


def control(op, value=None):
    value = value or {}
    if op == 'attach':
        return Files.prepare(value.get('urls', []))
    if op == 'paste':
        return Files.clipboard()
    if op == 'status':
        return status(value.get('generation'), value.get('aliases'))
    if op == 'connect':
        snapshot = status()
        if snapshot['online'] or not snapshot['installed']:
            return snapshot
        return control('start')
    if op in ('download', 'pause', 'unload', 'delete'):
        scope, _ = service()
        url = server_url(scope)
        model = value.get('model', '')
        catalogue = chat_models(
            get_json(url + '/v1/models?show_all=true'),
            catalogue=True,
            aliases=model_aliases(url),
        )
        entry = next((row for row in catalogue if row['id'] == model), None)
        if not entry:
            raise ValueError('This local chat model is no longer available.')
        model = entry['target']
        if op == 'download':
            if not entry['downloaded']:
                with request(
                    url + '/v1/pull',
                    dict(model_name=model, stream=True, subscribe=False),
                    timeout=30,
                ) as response:
                    job = json.load(response)
                if job.get('error'):
                    raise ValueError(str(job['error']))
        elif op == 'pause':
            with request(
                url + '/v1/downloads/control', dict(id='model:' + model, action='pause')
            ) as response:
                json.load(response)
        else:
            health = get_json(url + '/v1/health')
            loaded = next(
                (
                    row
                    for row in health.get('all_models_loaded', [])
                    if row.get('model_name') == model
                ),
                None,
            )
            if not loaded and op == 'unload':
                return status()
            if loaded and any(
                loaded.get(flag) for flag in ('is_busy', 'is_streaming', 'pinned')
            ):
                raise ValueError('This model is in use or pinned in Lemonade.')
            if op == 'delete':
                if not entry['downloaded']:
                    raise ValueError('This model is not downloaded.')
                if any(
                    job.get('model_name') == model and job.get('running')
                    for job in get_json(url + '/v1/downloads')
                ):
                    raise ValueError('Wait for this model to finish downloading.')
            with request(
                url + '/v1/' + op,
                dict(model_name=model),
                timeout=60 if op == 'delete' else 30,
            ) as response:
                json.load(response)
        return status()
    if op not in ('start', 'stop'):
        raise ValueError('Unknown assistant operation.')
    scope, state = service()
    if not scope:
        raise ValueError(
            'The Lemonade user service is unavailable. Install lemonade-server.'
        )
    if op == 'start' and state.get('ActiveState') in ('active', 'activating'):
        return status()
    if op == 'stop':
        snapshot = status()
        if any(row.get('busy') for row in snapshot.get('loaded', [])) or any(
            job.get('running') for job in snapshot.get('downloads', [])
        ):
            raise ValueError(
                'Lemonade is downloading or serving a request. Wait for it to finish before stopping.'
            )
    if op == 'stop' and state.get('ActiveState') not in (
        'active',
        'activating',
        'deactivating',
    ):
        snapshot = status()
        if snapshot['online']:
            raise ValueError(
                'Lemonade was started outside systemd. Stop it in the app or terminal that started it.'
            )
        return snapshot
    args = ['systemctl', *(['--user'] if scope == 'user' else []), op, UNIT]
    result = run(args, timeout=45)
    if result.returncode:
        raise ValueError(result.stderr.strip() or f'Could not {op} Lemonade.')
    # Type=simple reports started before its HTTP listener is ready.
    if op == 'start':
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            snapshot = status()
            if snapshot['online'] or snapshot['state'] == 'failed':
                return snapshot
            time.sleep(0.4)
    return status()


def events(response):
    """Decode SSE events, including CRLF, comments and multi-line data."""
    data = []
    for raw in response:
        line = raw.decode('utf-8').rstrip('\r\n')
        if not line:
            if data:
                yield '\n'.join(data)
                data = []
        elif line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
    if data:
        yield '\n'.join(data)


def chat(value):
    scope, _ = service()
    url = server_url(scope)
    model = value.get('model', '')
    # An explicit Send authorizes Lemonade's native download-and-load path for
    # this selected catalogue model. Never route local chat through cloud models.
    entry = next(
        (
            row
            for row in chat_models(
                get_json(url + '/v1/models?show_all=true'), catalogue=True
            )
            if row['id'] == model
        ),
        None,
    )
    if not entry:
        raise ValueError(
            'This local chat model is unavailable. Choose another model or open Lemonade.'
        )
    length = LENGTHS[value.get('length', 'brief')]
    messages = value.get('messages', [])
    if not messages or messages[-1].get('role') != 'user' or len(messages) > 80:
        raise ValueError('Start a new chat before continuing.')
    if any(
        row.get('role') not in ('user', 'assistant')
        or not isinstance(row.get('content'), str)
        for row in messages
    ):
        raise ValueError('Invalid chat messages.')
    converted = [
        dict(
            role=row['role'],
            content=Files.message_content(row, 'vision' in entry['labels']),
        )
        for row in messages
    ]
    if (
        len(json.dumps(converted).encode()) > Files.MAX_CONTEXT_BYTES
        or sum(
            len(row['content'])
            + sum(len(item.get('text', '')) for item in row.get('attachments', []))
            for row in messages
        )
        > Files.MAX_CONTEXT_TEXT
    ):
        raise ValueError(
            'This conversation is too large. Start a new chat or use smaller attachments.'
        )
    payload = dict(
        model=model,
        stream=True,
        messages=[
            dict(
                role='system',
                content=length,
            ),
            *converted,
        ],
    )
    thinking = value.get('thinking', 'auto')
    if thinking not in ('auto', 'on', 'off'):
        raise ValueError('Invalid thinking option.')
    # Catalogue labels are descriptive, not a reliable capability gate (some
    # Qwen entries omit "reasoning"). Let Lemonade handle its native control.
    if thinking != 'auto':
        payload['enable_thinking'] = thinking == 'on'
    style = value.get('style', 'default')
    if style not in ('default', 'precise', 'creative'):
        raise ValueError('Invalid response style.')
    if style != 'default':
        payload['temperature'] = 0.2 if style == 'precise' else 0.9
    done, finish, pending, reasoning, last = False, '', '', '', 0
    # A first-use download can take longer than inference. Stop still terminates
    # this client request; Lemonade owns the download.
    with request(
        url + '/v1/chat/completions',
        payload,
        timeout=600 if entry['downloaded'] else 3600,
    ) as response:
        for event in events(response):
            if event == '[DONE]':
                done = True
                break
            chunk = json.loads(event)
            if chunk.get('error'):
                error = chunk['error']
                raise ValueError(
                    error.get('message', str(error))
                    if isinstance(error, dict)
                    else str(error)
                )
            for choice in chunk.get('choices', []):
                delta = choice.get('delta', {})
                pending += delta.get('content') or ''
                reasoning += delta.get('reasoning_content') or ''
                finish = choice.get('finish_reason') or finish
            now = time.monotonic()
            if now - last >= 0.04:
                emit(
                    dict(
                        type='delta',
                        text=pending,
                        reasoning=reasoning,
                        thinking=bool(reasoning),
                    )
                )
                pending, reasoning, last = '', '', now
    if pending or reasoning:
        emit(
            dict(
                type='delta',
                text=pending,
                reasoning=reasoning,
                thinking=bool(reasoning),
            )
        )
    if not done and not finish:
        raise ValueError(
            'Lemonade disconnected before finishing. You can retry the reply.'
        )
    emit(dict(type='done', limited=finish == 'length'))


def main():
    try:
        value = json.loads(sys.stdin.readline())
        if value.get('op') == 'chat':
            chat(value)
        else:
            emit(control(value.get('op'), value))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get('error', {})
            message = (
                detail.get('message', '') if isinstance(detail, dict) else str(detail)
            )
        except (ValueError, OSError):
            message = ''
        emit(dict(type='error', error=message or f'Lemonade returned HTTP {exc.code}.'))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        emit(dict(type='error', error=str(exc)))


if __name__ == '__main__':
    main()
