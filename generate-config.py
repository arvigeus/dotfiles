#!/usr/bin/env python3
"""Merge the selected modules into user-configuration.json for archinstall."""

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parent
OUTPUT = REPO / 'user-configuration.json'
FRAGMENTS = ('config.json', 'config.jsonc', 'config.sh')
MARKERS = (
    *FRAGMENTS,
    'files',
    'symlinks',
    'scripts',
    'check.sh',
    'prerequisite.sh',
    'pre.sh',
)
# Native fields emitted by archinstall 4.5's ArchConfig.
CONFIG_KEYS = {
    'version',
    'script',
    'locale_config',
    'archinstall_language',
    'disk_config',
    'profile_config',
    'mirror_config',
    'network_config',
    'bootloader_config',
    'app_config',
    'auth_config',
    'swap',
    'hostname',
    'kernels',
    'firmware_optdeps',
    'ntp',
    'timezone',
    'services',
    'packages',
    'pacman_config',
    'custom_commands',
    'extra',
}
LIST_SETTINGS = {
    ('packages',),
    ('services',),
    ('custom_commands',),
    ('app_config', 'fonts_config', 'fonts'),
    ('mirror_config', 'custom_repositories'),
}
# A single archinstall custom command runs every module hook from the checkout.
CONFIGURE = 'bash "${DOTFILES_REPO:-$(dirname -- "$(readlink -f /run/system-configuration.json)")}/scripts/configure.sh"'


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
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
    return re.sub(
        r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])',
        lambda match: match[0] if match[0].startswith('"') else '',
        clean,
    )


def merge(target, incoming, source, path=()):
    for key, value in incoming.items():
        setting = (*path, key)
        if setting in LIST_SETTINGS or (
            path and path[0] == 'extra' and isinstance(value, list)
        ):
            strings_only = setting in LIST_SETTINGS and setting != (
                'mirror_config',
                'custom_repositories',
            )
            if not isinstance(value, list) or (
                strings_only and not all(isinstance(item, str) for item in value)
            ):
                raise ValueError(
                    f'{source}: {".".join(setting)} must be a list of strings'
                )
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
            raise ValueError(f'{source}: conflicting setting: {".".join(setting)}')


def discover(root, env):
    """Yield selected modules: the first directories below root that contain a marker."""
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        if not any((directory / name).exists() for name in MARKERS):
            yield from discover(directory, env)
            continue
        check = directory / 'check.sh'
        if check.exists():
            status = subprocess.run(
                ['bash', '-euo', 'pipefail', str(check), str(REPO)],
                env=env,
                cwd=directory,
            ).returncode
            if status == 1:
                continue
            if status:
                raise ValueError(
                    f'{check.relative_to(REPO)}: selection failed ({status})'
                )
        yield directory


def load_fragment(fragment, env, configure):
    if fragment.suffix == '.sh':
        command = ['bash', '-euo', 'pipefail', str(fragment)] + (
            ['--configure'] if configure else []
        )
        content = subprocess.check_output(
            command, cwd=fragment.parent, text=True, env=env
        )
    else:
        content = fragment.read_text()
    if fragment.suffix == '.jsonc':
        content = strip_comments(content)
    data = json.loads(content, object_pairs_hook=unique_keys)
    source = fragment.relative_to(REPO)
    if not isinstance(data, dict):
        raise ValueError(f'{source}: expected a JSON object')
    if unknown := data.keys() - CONFIG_KEYS:
        raise ValueError(
            f'{source}: unsupported archinstall options: {", ".join(sorted(unknown))}'
        )
    return data


def hook(path):
    subprocess.run(['bash', '-n', str(path)], check=True)
    return path.relative_to(REPO).as_posix()


def collect(module_dirs, extra):
    """Add module assets and hooks to extra; every destination has one owner."""
    for directory in module_dirs:
        for kind in ('files', 'symlinks'):
            for source in sorted((directory / kind).rglob('*')):
                asset = source.relative_to(directory / kind)
                if (
                    not source.is_file()
                    or '__pycache__' in asset.parts
                    or asset.suffix in ('.pyc', '.pyo')
                ):
                    continue
                target = (
                    asset.as_posix()
                    if asset.parts[0] == 'home'
                    else '/' + asset.as_posix()
                )
                entry = {
                    'source': source.relative_to(REPO).as_posix(),
                    'target': target,
                }
                if kind == 'files':
                    entry['mode'] = '0755' if source.stat().st_mode & 0o111 else '0644'
                extra[kind].append(entry)
        for name, kind in (('prerequisite.sh', 'checks'), ('pre.sh', 'pre')):
            if (directory / name).is_file():
                extra[kind].append(hook(directory / name))
    # Hooks run in one global order: by filename, then by module path.
    scripts = sorted(
        (
            script
            for directory in module_dirs
            for script in (directory / 'scripts').glob('*.sh')
        ),
        key=lambda script: (script.name, script.relative_to(REPO).as_posix()),
    )
    extra['scripts'] = [hook(script) for script in scripts]
    validate_assets(extra)


def validate_assets(extra):
    """Check explicit and discovered assets before publishing the manifest."""
    destinations = set()
    for kind in ('files', 'symlinks'):
        for entry in extra[kind]:
            source, target = entry['source'], entry['target']
            path = PurePosixPath(target)
            if (
                path.as_posix() != target
                or '..' in path.parts
                or target in ('/', 'home')
                or target.startswith('//')
                or not (target.startswith('/') or target.startswith('home/'))
                or any(char in source + target for char in '\n\r\t\0')
            ):
                raise ValueError(f'Invalid asset path: {source!r} -> {target!r}')
            asset = REPO / source
            if (
                PurePosixPath(source).is_absolute()
                or not asset.is_file()
                or not asset.resolve().is_relative_to(REPO.resolve())
            ):
                raise ValueError(
                    f'Asset source must be a file inside the checkout: {source}'
                )
            if target in destinations:
                raise ValueError(f'Multiple modules provide {target}')
            destinations.add(target)
    for target in sorted(destinations):
        if any(
            parent.as_posix() in destinations
            for parent in PurePosixPath(target).parents
        ):
            raise ValueError(f'Asset destination overlaps another file: {target}')


def write_atomic(path, text):
    with tempfile.NamedTemporaryFile(
        mode='w', dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(text)
            temporary.close()
            temporary_path.chmod(0o644)
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', nargs='?', default=None)
    parser.add_argument(
        '--configure',
        action='store_true',
        help='Prompt for dynamic module settings again',
    )
    args = parser.parse_args()

    host = (
        args.host
        or os.environ.get('DOTFILES_HOST')
        or (REPO / 'host').read_text().strip()
    )
    if (
        not re.fullmatch(r'[a-zA-Z0-9_-]+', host)
        or not (REPO / 'modules/hosts' / host).is_dir()
    ):
        raise ValueError(f'Unknown host: {host}')
    env = dict(os.environ, DOTFILES_HOST=host)
    env.setdefault('DOTFILES_DESKTOP', 'hyprland')

    module_dirs = list(discover(REPO / 'modules', env))
    config = {}
    for directory in module_dirs:
        for name in FRAGMENTS:
            fragment = directory / name
            if fragment.is_file():
                merge(
                    config,
                    load_fragment(fragment, env, args.configure),
                    fragment.relative_to(REPO),
                )
    if not config:
        raise ValueError('No module configuration found')

    extra = config.setdefault('extra', {})
    extra['host'] = host
    extra.setdefault('desktop', env['DOTFILES_DESKTOP'])
    for name in ('files', 'symlinks', 'aur_packages', 'checks', 'pre'):
        extra.setdefault(name, [])
    extra.setdefault('flatpak', {}).setdefault('remotes', {})
    extra['flatpak'].setdefault('packages', [])
    collect(module_dirs, extra)
    config['custom_commands'] = [CONFIGURE] + config.get('custom_commands', [])

    write_atomic(OUTPUT, json.dumps(dict(sorted(config.items())), indent=4) + '\n')
    print(OUTPUT)


if __name__ == '__main__':
    main()
