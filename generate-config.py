#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

repo = Path(__file__).resolve().parent
config = {}
parser = argparse.ArgumentParser(description='Merge module configuration for archinstall.')
parser.add_argument('host', nargs='?', default=None)
parser.add_argument('--configure', action='store_true', help='Prompt for dynamic module settings again')
args = parser.parse_args()
selection_env = dict(os.environ)
if args.host is not None:
    selection_env['DOTFILES_HOST'] = args.host

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
    clean = tokens.sub(replace, content)
    # JSONC fragments may use trailing commas; quoted values remain untouched.
    return re.sub(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])',
                  lambda match: match[0] if match[0].startswith('"') else '', clean)


LIST_SETTINGS = {
    ('packages',), ('services',), ('custom_commands',),
    ('app_config', 'fonts_config', 'fonts'),
    ('mirror_config', 'custom_repositories'),
}

# Native fields emitted by archinstall 4.5's ArchConfig.
CONFIG_KEYS = {
    'version', 'script', 'locale_config', 'archinstall_language', 'disk_config',
    'profile_config', 'mirror_config', 'network_config', 'bootloader_config',
    'app_config', 'auth_config', 'swap', 'hostname', 'kernels', 'firmware_optdeps',
    'ntp', 'timezone', 'services', 'packages', 'pacman_config', 'custom_commands', 'extra',
}


def merge(target, incoming, source, path=()):
    for key, value in incoming.items():
        setting = (*path, key)
        if setting in LIST_SETTINGS or (path and path[0] == 'extra' and isinstance(value, list)):
            if not isinstance(value, list) or (setting in LIST_SETTINGS and setting != ('mirror_config', 'custom_repositories') and not all(isinstance(item, str) for item in value)):
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
        elif target[key] != value:
            raise ValueError(f"{source}: conflicting setting: {'.'.join(setting)}")

selected_host = args.host or os.environ.get('DOTFILES_HOST') or (repo / 'host').read_text().strip()
if not re.fullmatch(r'[a-zA-Z0-9_-]+', selected_host) or not (repo / 'modules/hosts' / selected_host).is_dir():
    raise ValueError(f'Unknown host: {selected_host}')
selection_env['DOTFILES_HOST'] = selected_host
selection_env.setdefault('DOTFILES_DESKTOP', 'hyprland')
module_dirs = []
def discover(root):
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        markers = ('config.json', 'config.jsonc', 'config.sh', 'files', 'symlinks', 'scripts', 'check.sh', 'prerequisite.sh', 'pre.sh')
        if any((directory / name).exists() for name in markers) or list(directory.glob('*.config.json*')):
            check = directory / 'check.sh'
            if check.exists():
                result = subprocess.run(['bash', '-euo', 'pipefail', str(check), str(repo)], env=selection_env, cwd=directory)
                if result.returncode == 1:
                    continue
                if result.returncode:
                    raise ValueError(f'{check.relative_to(repo)}: selection failed ({result.returncode})')
            module_dirs.append(directory)
        else:
            discover(directory)
discover(repo / 'modules')
fragments = [
    fragment
    for directory in module_dirs
    for fragment in sorted(
        path for name in ('config.json', 'config.jsonc', '*.config.json', '*.config.jsonc', 'config.sh')
        for path in directory.glob(name)
    )
]
for fragment in fragments:
    source = fragment.relative_to(repo)
    if fragment.suffix == '.sh':
        content = subprocess.check_output(
            ['bash', '-euo', 'pipefail', str(fragment)] + (['--configure'] if args.configure else []),
            cwd=fragment.parent, text=True,
            env=dict(os.environ, DOTFILES_HOST=selected_host),
        )
    else:
        content = fragment.read_text()
    if fragment.suffix == '.jsonc':
        content = strip_comments(content)
    data = json.loads(content, object_pairs_hook=unique_keys)
    if not isinstance(data, dict):
        raise ValueError(f"{source}: expected a JSON object")
    if unknown := data.keys() - CONFIG_KEYS:
        raise ValueError(f"{source}: unsupported archinstall options: {', '.join(sorted(unknown))}")
    merge(config, data, source)

if not config:
    raise ValueError('No module configuration found')

extra = config.setdefault('extra', {})
extra['host'] = selected_host
extra.setdefault('desktop', os.environ.get('DOTFILES_DESKTOP', 'hyprland'))
for name in ('files', 'symlinks', 'aur_packages', 'checks', 'pre'):
    extra.setdefault(name, [])
flatpak = extra.setdefault('flatpak', {})
flatpak.setdefault('remotes', {})
flatpak.setdefault('packages', [])


def compile_script(path):
    """Snapshot hooks and their shared helpers; never load module code at apply time."""
    text = path.read_text()
    text = re.sub(r'^MODULE_DIR=\$\(cd .*\n', '', text, flags=re.MULTILINE)
    source = re.compile(r'^source "\$repo_dir/(scripts/[^"\n]+)"\s*$', re.MULTILINE)
    return source.sub(lambda match: compile_script(repo / match[1]), text)


destinations = set()
for kind in ('files', 'symlinks'):
    for entry in extra[kind]:
        if entry['target'] in destinations:
            raise ValueError(f"Multiple modules provide {entry['target']}")
        destinations.add(entry['target'])
for directory in module_dirs:
    module = directory.relative_to(repo).as_posix()
    for kind in ('files', 'symlinks'):
        for source in sorted((directory / kind).rglob('*')):
            if not source.is_file():
                continue
            asset = source.relative_to(directory / kind)
            if '__pycache__' in asset.parts or asset.suffix in ('.pyc', '.pyo'):
                continue
            relative = asset.as_posix()
            target = relative if relative.startswith('home/') else '/' + relative
            if target in destinations:
                raise ValueError(f'Multiple modules provide {target}')
            destinations.add(target)
            entry = {'source': source.relative_to(repo).as_posix(), 'target': target}
            if kind == 'files':
                entry['mode'] = '0440' if target.startswith('/etc/sudoers.d/') else '0755' if source.stat().st_mode & 0o111 else '0644'
            extra[kind].append(entry)
    pre = directory / 'pre.sh'
    if pre.is_file():
        body = compile_script(pre)
        subprocess.run(['bash', '-n'], input=body, text=True, check=True)
        extra['pre'].append({'module': module, 'script': body})
    hook = directory / 'prerequisite.sh'
    if hook.is_file():
        extra['checks'].append({'module': module, 'script': compile_script(hook)})

import shlex
entrypoint = 'bash "$(dirname -- "$(readlink -f /run/system-configuration.json)")/user-configuration.sh"'
commands = [entrypoint + ' --prepare']
script_paths = sorted((script for directory in module_dirs for script in (directory / 'scripts').glob('*.sh')),
                      key=lambda script: (script.name, script.relative_to(repo).as_posix()))
for script in script_paths:
    body = compile_script(script)
    subprocess.run(['bash', '-n'], input=body, text=True, check=True)
    commands.append(entrypoint + ' --run ' + shlex.quote(script.parent.parent.relative_to(repo).as_posix()) + ' ' + shlex.quote(body))
commands.append(entrypoint + ' --finish')
config['custom_commands'] = commands + config.get('custom_commands', [])
executor = (repo / 'scripts/templates/user-configuration.sh').read_text()
executor = executor.replace('@@EXTRA_PACKAGES@@', (repo / 'scripts/templates/extra-packages.sh').read_text())
executor = executor.replace('@@PUBLISH_HOME@@', (repo / 'scripts/publish-home.py').read_text())
subprocess.run(['bash', '-n'], input=executor, text=True, check=True)

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
executor_path = repo / 'user-configuration.sh'
with tempfile.NamedTemporaryFile(mode='w', dir=repo, delete=False) as temporary:
    temporary_path = Path(temporary.name)
    try:
        temporary.write(executor)
        temporary.close()
        temporary_path.chmod(0o755)
        temporary_path.replace(executor_path)
    finally:
        temporary_path.unlink(missing_ok=True)
print(executor_path)
