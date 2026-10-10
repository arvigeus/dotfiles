#!/usr/bin/env python3
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

repo = Path(__file__).resolve().parent
config = {}

def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result

def strip_comments(content):
    # Match quoted strings first so URLs and comment markers inside them survive.
    tokens = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.DOTALL)
    def replace(match):
        token = match.group()
        if token.startswith('"'):
            return token
        return ''.join('\n' if char == '\n' else ' ' for char in token)
    return tokens.sub(replace, content)


LIST_SETTINGS = {
    ('packages',), ('services',), ('custom_commands',),
    ('app_config', 'fonts_config', 'fonts'),
}


def merge(target, incoming, source, path=()):
    for key, value in incoming.items():
        setting = (*path, key)
        if setting in LIST_SETTINGS:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{source}: {'.'.join(setting)} must be a list of strings")
            existing = target.setdefault(key, [])
            for item in value:
                if setting == ('custom_commands',) or item not in existing:
                    existing.append(item)
        elif key not in target:
            if isinstance(value, dict):
                target[key] = {}
                merge(target[key], value, source, setting)
            else:
                target[key] = value
        elif isinstance(target[key], dict) and isinstance(value, dict):
            merge(target[key], value, source, setting)
        else:
            raise ValueError(f"{source}: repeated setting: {'.'.join(setting)}")

fragments = sorted(
    [*(repo / 'modules').rglob('config.json'),
     *(repo / 'modules').rglob('config.jsonc'),
     *(repo / 'modules').rglob('config.sh')]
)
for fragment in fragments:
    source = fragment.relative_to(repo)
    if fragment.suffix == '.sh':
        content = subprocess.check_output(
            ['bash', '-euo', 'pipefail', str(fragment)],
            cwd=fragment.parent, text=True,
        )
    else:
        content = fragment.read_text()
    if fragment.suffix == '.jsonc':
        content = strip_comments(content)
    data = json.loads(content, object_pairs_hook=unique_keys)
    if not isinstance(data, dict):
        raise ValueError(f"{source}: expected a JSON object")
    merge(config, data, source)

if not config:
    raise ValueError('No module configuration found')

output = repo / 'user-configuration.json'
with tempfile.NamedTemporaryFile(mode='w', dir=repo, delete=False) as temporary:
    temporary_path = Path(temporary.name)
    try:
        json.dump(dict(sorted(config.items())), temporary, indent=4)
        temporary.write('\n')
        temporary.close()
        os.chmod(temporary_path, 0o644)
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)
print(output)
