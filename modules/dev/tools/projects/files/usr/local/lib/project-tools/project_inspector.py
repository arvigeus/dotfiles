"""Bounded, stateless project inspection without evaluating project configuration."""

import json
import os
import re
import shutil
import subprocess
import tomllib
from itertools import islice
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from project_tasks import discover

LANGUAGE_EXCLUDES = (
    '.git',
    '.hg',
    '.svn',
    'node_modules',
    'target',
    'dist',
    'build',
    '.next',
    '.nuxt',
    '.turbo',
    '.syntaxis-worktrees',
    '.venv',
    'venv',
    'vendor',
    'coverage',
    '__pycache__',
)


def language_summary(root):
    try:
        scanner = shutil.which('tokei') or str(
            Path(os.environ.get('CARGO_HOME', Path.home() / '.local/share/cargo'))
            / 'bin/tokei'
        )
        command = [scanner, '--output', 'json', '--hidden']
        for directory in LANGUAGE_EXCLUDES:
            command.extend(['--exclude', directory])
        result = subprocess.run(
            [*command, '--', str(root)],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise TypeError('Invalid language report.')
        return language_report(root, data), []
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return {'languages': [], 'partial': False}, ['Language analysis unavailable.']


def language_report(root, data):
    """Adapt Tokei's file reports to byte shares without recounting embedded languages."""
    root = Path(root).resolve()
    seen = set()
    totals = {}
    partial = False
    names = {
        'BASH': 'Shell',
        'Bash': 'Shell',
        'Sh': 'Shell',
        'Zsh': 'Shell',
        'Cpp': 'C++',
        'C Header': 'C',
        'CHeader': 'C',
        'C++ Header': 'C++',
        'CppHeader': 'C++',
        'CSharp': 'C#',
        'TSX': 'TypeScript',
        'Tsx': 'TypeScript',
        'JSX': 'JavaScript',
        'Jsx': 'JavaScript',
        'Html': 'HTML',
        'Css': 'CSS',
        'Qml': 'QML',
    }
    for kind, language in data.items():
        if kind == 'Total':
            continue
        if not isinstance(language, dict) or not isinstance(
            language.get('reports'), list
        ):
            raise TypeError('Invalid language report.')
        partial |= bool(language.get('inaccurate'))
        name = names.get(kind, kind)
        for report in language['reports']:
            path = Path(report['name'])
            if not path.is_absolute():
                path = root / path
            try:
                resolved = path.resolve()
                if (
                    not resolved.is_relative_to(root)
                    or path.is_symlink()
                    or resolved in seen
                ):
                    continue
                size = path.stat().st_size
            except OSError:
                partial = True
                continue
            seen.add(resolved)
            total = totals.setdefault(name, [0, 0])
            total[0] += size
            total[1] += 1
    total_bytes = sum(total[0] for total in totals.values())
    languages = [
        dict(
            name=name,
            bytes=size,
            files=files,
            percentage=100 * size / total_bytes if total_bytes else 0,
            color=TECH.get(name, ('#808080', ''))[0],
        )
        for name, (size, files) in totals.items()
    ]
    languages.sort(key=lambda language: (-language['bytes'], language['name']))
    return dict(
        languages=languages,
        total_bytes=total_bytes,
        scanned_files=len(seen),
        partial=partial,
    )


MISE_CONFIGS = (
    'mise.toml',
    '.mise.toml',
    '.mise/config.toml',
    '.config/mise/config.toml',
    'mise.local.toml',
    '.mise.local.toml',
    '.mise/config.local.toml',
    '.config/mise/config.local.toml',
)
TECH = {
    'Rust': ('#ce7953', 'text-rust'),
    'JavaScript': ('#b58b13', 'text-x-javascript'),
    'TypeScript': ('#3178c6', 'text-x-typescript'),
    'Python': ('#4383b2', 'text-x-python'),
    'Go': ('#008fa8', 'text-x-go'),
    'C / C++': ('#626ac5', 'text-x-c++src'),
    'C# / .NET': ('#9160c2', 'text-x-csharp'),
    'Java': ('#bd643b', 'text-x-java'),
    'Kotlin': ('#9670dc', 'text-x-kotlin'),
    'Ruby': ('#c55659', 'text-x-ruby'),
    'PHP': ('#777bb3', 'text-x-php'),
    'Dart / Flutter': ('#329ac4', 'text-x-dart'),
    'Swift': ('#d87640', 'text-x-swift'),
    'React': ('#2499b4', 'applications-development'),
    'Next.js': ('#777777', 'applications-development'),
    'Vue': ('#37956d', 'applications-development'),
    'Nuxt': ('#369e75', 'applications-development'),
    'Svelte': ('#d76b37', 'applications-development'),
    'Astro': ('#a26ac5', 'applications-development'),
    'Angular': ('#c54e69', 'applications-development'),
    'Dioxus': ('#b16a52', 'applications-development'),
    'Tauri': ('#298ea5', 'applications-development'),
    'Django': ('#478365', 'applications-development'),
    'FastAPI': ('#36998c', 'applications-development'),
    'Qt / QML': ('#559b51', 'QtProject-qtcreator'),
    'Docker': ('#348bc2', 'docker'),
    'Nix': ('#639ac4', 'nix-snowflake'),
    'Terraform': ('#8562bd', 'applications-development'),
    'Shell': ('#629456', 'utilities-terminal'),
    'Mise': ('#a47d37', 'applications-development'),
}


def local_file(root, relative, limit=1024 * 1024):
    path = root / relative
    try:
        if (
            not path.resolve().is_relative_to(root.resolve())
            or not path.is_file()
            or path.stat().st_size > limit
        ):
            return None
        return path
    except OSError:
        return None


def read_data(root, relative):
    path = local_file(root, relative)
    if path is None:
        return {}
    try:
        data = (
            json.loads(path.read_text())
            if path.suffix == '.json'
            else tomllib.loads(path.read_text())
        )
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, ValueError):
        return {}


def git_read(root, *arguments):
    result = subprocess.run(
        [
            'git',
            '--no-optional-locks',
            '-c',
            'core.fsmonitor=false',
            '-C',
            str(root),
            *arguments,
        ],
        check=False,
        capture_output=True,
        timeout=5,
        env=dict(os.environ, GIT_TERMINAL_PROMPT='0'),
    )
    if result.returncode:
        raise ValueError('Git information unavailable.')
    return result.stdout.decode(errors='replace')


def remote_info(url):
    """Expose a browser URL without remote credentials or local filesystem paths."""
    match = re.fullmatch(r'(?:[^/@:]+@)?([\w.-]+):([^\s]+)', url)
    if (
        match
        and '://' not in url
        and '::' not in url
        and not url.startswith(('/', './', '../'))
    ):
        url = 'https://' + match[1] + '/' + match[2]
    parts = urlsplit(url)
    if parts.scheme not in ('https', 'http', 'ssh') or not parts.hostname:
        return {'label': 'Local or custom remote', 'url': ''}
    host = parts.hostname
    if ':' in host:
        host = '[' + host + ']'
    # SSH ports generally do not identify the forge's web server.
    if parts.scheme != 'ssh' and parts.port:
        host += ':' + str(parts.port)
    path = parts.path.removesuffix('.git')
    safe = urlunsplit(
        ('https' if parts.scheme == 'ssh' else parts.scheme, host, path, '', '')
    )
    return {'label': host + path, 'url': safe}


def git_status(root):
    raw = git_read(
        root, 'status', '--porcelain=v2', '--branch', '-z', '--untracked-files=normal'
    )
    result = {
        'branch': '',
        'head': '',
        'upstream': '',
        'ahead': 0,
        'behind': 0,
        'staged': 0,
        'modified': 0,
        'untracked': 0,
        'conflicts': 0,
        'latest': '',
        'remote': {'label': '', 'url': ''},
        'remote_name': '',
        'operation': '',
    }
    records = iter(raw.split('\0'))
    for record in records:
        if record.startswith('# branch.head '):
            result['branch'] = record[14:]
        elif record.startswith('# branch.oid '):
            result['head'] = record[13:]
        elif record.startswith('# branch.upstream '):
            result['upstream'] = record[18:]
        elif record.startswith('# branch.ab '):
            ahead, behind = record[12:].split()
            result['ahead'], result['behind'] = int(ahead[1:]), int(behind[1:])
        elif record.startswith(('1 ', '2 ')):
            x, y = record[2:4]
            result['staged'] += x != '.'
            result['modified'] += y != '.'
            if record.startswith('2 '):
                next(records, None)
        elif record.startswith('? '):
            result['untracked'] += 1
        elif record.startswith('u '):
            result['conflicts'] += 1
    if result['branch'] == '(detached)':
        result['branch'] = 'Detached · ' + result['head'][:8]
    git_dir = Path(git_read(root, 'rev-parse', '--absolute-git-dir').strip())
    for marker, operation in [
        ('rebase-merge', 'Rebase in progress'),
        ('rebase-apply', 'Rebase in progress'),
        ('MERGE_HEAD', 'Merge in progress'),
        ('CHERRY_PICK_HEAD', 'Cherry-pick in progress'),
        ('REVERT_HEAD', 'Revert in progress'),
        ('BISECT_LOG', 'Bisect in progress'),
    ]:
        if (git_dir / marker).exists():
            result['operation'] = operation
            break
    try:
        result['latest'] = git_read(root, 'log', '-1', '--format=%h  %s').strip()
    except ValueError:
        pass
    try:
        branch = result['branch']
        remote = git_read(root, 'config', '--get', f'branch.{branch}.remote').strip()
        result['remote_name'] = remote
        result['remote'] = (
            {'label': 'Local tracking branch', 'url': ''}
            if remote == '.'
            else remote_info(git_read(root, 'remote', 'get-url', '--', remote).strip())
        )
    except (ValueError, subprocess.SubprocessError):
        try:
            result['remote'] = remote_info(
                git_read(root, 'remote', 'get-url', 'origin').strip()
            )
            result['remote_name'] = 'origin'
        except (ValueError, subprocess.SubprocessError):
            pass
    return result


def sync_action(state):
    if state['upstream'] and not state['branch'].startswith('Detached'):
        if state['behind'] and not state['ahead']:
            return 'pull'
        if state['ahead'] and not state['behind']:
            return 'push'
    return 'fetch'


def mise_info(root):
    tools, tasks, configs = {}, {}, []
    versions = local_file(root, '.tool-versions', 65536)
    if versions:
        configs.append('.tool-versions')
        for line in versions.read_text(errors='replace').splitlines():
            parts = line.split('#', 1)[0].split()
            if len(parts) > 1:
                tools[parts[0]] = ' '.join(parts[1:])
    for relative in MISE_CONFIGS:
        if local_file(root, relative) is None:
            continue
        configs.append(relative)
        data = read_data(root, relative)
        configured_tools = data.get('tools', {})
        if isinstance(configured_tools, dict):
            for name, value in configured_tools.items():
                if isinstance(value, dict):
                    value = value.get('version', 'configured locally')
                if isinstance(value, list):
                    value = ', '.join(
                        str(
                            v.get('version', 'configured') if isinstance(v, dict) else v
                        )
                        for v in value
                    )
                tools[name] = str(value)
        configured_tasks = data.get('tasks', {})
        if isinstance(configured_tasks, dict):
            for name, value in configured_tasks.items():
                if isinstance(value, dict) and value.get('hide'):
                    continue
                description = (
                    value.get('description', '') if isinstance(value, dict) else ''
                )
                tasks[name] = {
                    'name': name,
                    'description': str(description),
                    'source': relative,
                }
    # Conventional file tasks are inspected, never executed. Bound depth and count.
    for directory in ('mise-tasks', '.mise/tasks', '.config/mise/tasks'):
        base = root / directory
        if (
            not base.is_dir()
            or base.is_symlink()
            or not base.resolve().is_relative_to(root.resolve())
        ):
            continue
        pending = [(base, 0)]
        visited = 0
        while pending and visited < 128:
            folder, depth = pending.pop()
            for path in sorted(islice(folder.iterdir(), 128)):
                if visited >= 128:
                    break
                visited += 1
                if path.is_symlink():
                    continue
                if path.is_dir() and depth < 2:
                    pending.append((path, depth + 1))
                elif path.is_file() and os.access(path, os.X_OK):
                    name = path.relative_to(base).as_posix().replace('/', ':')
                    tasks.setdefault(
                        name,
                        {
                            'name': name,
                            'description': 'File task',
                            'source': path.relative_to(root).as_posix(),
                        },
                    )
        if visited and directory not in configs:
            configs.append(directory)
    return {
        'tools': [{'name': k, 'version': v} for k, v in sorted(tools.items())],
        'tasks': sorted(tasks.values(), key=lambda t: t['name']),
        'configs': configs,
    }


def inspect(path):
    selected = Path(path).resolve()
    errors = []
    try:
        root = Path(
            git_read(selected, 'rev-parse', '--show-toplevel').strip()
        ).resolve()
    except (ValueError, OSError, subprocess.SubprocessError):
        root = None
    working = root or selected
    found = {}

    def add(name, evidence):
        found.setdefault(name, []).append(evidence)

    package = read_data(working, 'package.json')
    cargo = read_data(working, 'Cargo.toml')
    python = read_data(working, 'pyproject.toml')
    name, description, version = working.name, '', ''
    metadata = package or python.get('project', {}) or cargo.get('package', {})
    if isinstance(metadata, dict):
        name = metadata.get('name', name)
        description = metadata.get('description', '')
        version = metadata.get('version', '')
        if not isinstance(version, str):
            version = ''
    if local_file(working, 'package.json'):
        add('JavaScript', 'package.json')
        dependencies = {}
        for key in ('dependencies', 'devDependencies', 'peerDependencies'):
            if isinstance(package.get(key), dict):
                dependencies.update(package[key])
        for dependency, tech in {
            'typescript': 'TypeScript',
            'react': 'React',
            'next': 'Next.js',
            'vue': 'Vue',
            'nuxt': 'Nuxt',
            'svelte': 'Svelte',
            'astro': 'Astro',
            '@angular/core': 'Angular',
            '@tauri-apps/api': 'Tauri',
        }.items():
            if dependency in dependencies:
                add(tech, 'package.json · ' + dependency)
    if local_file(working, 'tsconfig.json'):
        add('TypeScript', 'tsconfig.json')
    manifests = ['Cargo.toml', 'src-tauri/Cargo.toml']
    workspace = cargo.get('workspace', {})
    if isinstance(workspace, dict):
        members = workspace.get('members', [])
        if isinstance(members, list):
            manifests += [
                m + '/Cargo.toml'
                for m in members[:48]
                if isinstance(m, str) and '*' not in m
            ]
    for relative in dict.fromkeys(manifests):
        manifest = local_file(working, relative)
        if not manifest:
            continue
        add('Rust', relative)
        data = read_data(working, relative)
        deps = {}
        for group in [data, data.get('workspace', {})]:
            if not isinstance(group, dict):
                continue
            for key in ('dependencies', 'dev-dependencies', 'build-dependencies'):
                if isinstance(group.get(key), dict):
                    deps.update(group[key])
        for dep, tech in [('dioxus', 'Dioxus'), ('tauri', 'Tauri')]:
            if dep in deps:
                add(tech, relative + ' · ' + dep)
    markers = {
        'Python': ['pyproject.toml', 'requirements.txt', 'setup.py', 'Pipfile'],
        'Go': ['go.mod'],
        'C / C++': ['CMakeLists.txt', 'meson.build', 'configure.ac'],
        'Java': ['pom.xml'],
        'Kotlin': ['build.gradle.kts'],
        'Ruby': ['Gemfile'],
        'PHP': ['composer.json'],
        'Dart / Flutter': ['pubspec.yaml'],
        'Swift': ['Package.swift'],
        'Docker': [
            'Dockerfile',
            'compose.yaml',
            'compose.yml',
            'docker-compose.yml',
            'docker-compose.yaml',
        ],
        'Nix': ['flake.nix', 'shell.nix', 'default.nix'],
        'Qt / QML': ['qmldir'],
    }
    for tech, paths in markers.items():
        for relative in paths:
            if local_file(working, relative):
                add(tech, relative)
    for entry in sorted(islice(working.iterdir(), 256)):
        if not local_file(working, entry.name):
            continue
        if entry.suffix in ('.csproj', '.sln', '.fsproj'):
            add('C# / .NET', entry.name)
        elif entry.suffix == '.tf':
            add('Terraform', entry.name)
        elif entry.suffix == '.sh':
            add('Shell', entry.name)
        elif entry.suffix == '.qml':
            add('Qt / QML', entry.name)
    project = python.get('project', {})
    if isinstance(project, dict):
        dependencies = project.get('dependencies', [])
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if not isinstance(dependency, str):
                    continue
                dep = re.split(r'[<>=!~\[ ;]', dependency.lower(), maxsplit=1)[0]
                if dep in ('django', 'fastapi'):
                    add(
                        {'django': 'Django', 'fastapi': 'FastAPI'}[dep],
                        'pyproject.toml',
                    )
    mise = mise_info(working)
    task_list, task_notes = discover(working, mise['tasks'])
    languages, language_notes = language_summary(working)
    errors.extend(task_notes + language_notes)
    if mise['configs']:
        add('Mise', ', '.join(mise['configs']))
    managers = []
    for filename, manager in [
        ('bun.lock', 'Bun'),
        ('bun.lockb', 'Bun'),
        ('pnpm-lock.yaml', 'pnpm'),
        ('yarn.lock', 'Yarn'),
        ('package-lock.json', 'npm'),
        ('uv.lock', 'uv'),
        ('poetry.lock', 'Poetry'),
        ('Cargo.lock', 'Cargo'),
        ('go.sum', 'Go modules'),
    ]:
        if local_file(working, filename) and manager not in managers:
            managers.append(manager)
    if not description:
        readme = next(
            (
                local_file(working, p, 262144)
                for p in ['README.md', 'readme.md']
                if local_file(working, p, 262144)
            ),
            None,
        )
        if readme:
            for paragraph in re.split(r'\n\s*\n', readme.read_text(errors='replace')):
                text = paragraph.strip()
                if not text or text.startswith(
                    ('#', '<', '[', '!', '|', '`', '- ', '* ')
                ):
                    continue
                description = re.sub(
                    r'\[([^\]]+)\]\([^)]*\)', r'\1', ' '.join(text.split())
                )
                description = description.replace('**', '').replace('`', '')[:250]
                break
    icon = next(
        (
            str(local_file(working, p, 2 * 1024 * 1024))
            for p in [
                'favicon.svg',
                'logo.svg',
                'icon.svg',
                'assets/favicon.svg',
                'assets/logo.svg',
                'assets/icon.png',
                'favicon.ico',
                'public/favicon.svg',
                'public/favicon.ico',
                'static/favicon.png',
                'assets/favicon-96x96.png',
            ]
            if local_file(working, p, 2 * 1024 * 1024)
        ),
        '',
    )
    state = None
    if root:
        try:
            state = git_status(root)
        except (ValueError, OSError, subprocess.SubprocessError):
            errors.append('Git status could not be read. Refresh to try again.')
    return {
        'path': str(working),
        'git_root': str(root) if root else None,
        'name': str(name),
        'description': str(description),
        'version': version,
        'technologies': [
            {
                'name': tech,
                'color': TECH[tech][0],
                'icon': TECH[tech][1],
                'evidence': list(dict.fromkeys(evidence)),
            }
            for tech, evidence in found.items()
        ],
        'icon': icon,
        'managers': managers,
        'mise': mise,
        'tasks': task_list,
        'languages': languages,
        'git': state,
        'errors': errors,
    }
