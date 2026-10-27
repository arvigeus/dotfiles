"""Discover task declarations without running recipes or evaluating Makefiles."""

import json
import re
import shutil
import subprocess
from pathlib import Path

LABELS = {'mise': 'Mise', 'package': 'Package', 'make': 'Make', 'just': 'Just'}


def local(root, relative):
    path = root / relative
    try:
        if (
            path.resolve().is_relative_to(root.resolve())
            and path.is_file()
            and path.stat().st_size <= 1024 * 1024
        ):
            return path
    except OSError:
        pass
    return None


def package_data(root):
    path = local(root, 'package.json')
    try:
        data = json.loads(path.read_text()) if path else {}
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def package_manager(root, data):
    declared = data.get('packageManager', '')
    if isinstance(declared, str):
        name = declared.split('@', 1)[0]
        if name in ('bun', 'pnpm', 'yarn', 'npm'):
            return name
    for filename, manager in [
        ('bun.lock', 'bun'),
        ('bun.lockb', 'bun'),
        ('pnpm-lock.yaml', 'pnpm'),
        ('yarn.lock', 'yarn'),
    ]:
        if local(root, filename):
            return manager
    return 'npm'


def entry(runner, name, description, source, parameters='', tool=None):
    return {
        'runner': runner,
        'name': name,
        'description': description,
        'source': source,
        'parameters': parameters,
        'tool': tool or LABELS[runner],
    }


def make_tasks(root):
    tasks, visited = {}, set()

    def parse(relative, depth=0):
        path = local(root, relative)
        if not path or path in visited or len(visited) >= 16 or depth > 4:
            return
        visited.add(path)
        text = path.read_text(errors='replace').replace('\\\n', ' ')
        documentation, defining = [], False
        for line in text.splitlines():
            if line.startswith('\t'):
                continue
            text = line.strip()
            if re.match(r'^(?:override\s+|export\s+)?define\b', text):
                defining = True
            if text == 'endef':
                defining = False
                continue
            if defining:
                continue
            if text.startswith('#'):
                documentation.append(text.lstrip('#').strip())
                continue
            include = re.match(r'^(?:-?include|sinclude)\s+(.+?)(?:\s+#.*)?$', text)
            if include:
                for filename in include[1].split():
                    if not any(c in filename for c in '$*?[]'):
                        parse(filename, depth + 1)
                documentation = []
                continue
            match = re.match(r'^([^\s:#=]+(?:[ \t]+[^\s:#=]+)*)\s*:(?![=])', line)
            if match:
                names = match[1].split()
                inline = line.split('##', 1)[1].strip() if '##' in line else ''
                description = inline or ' '.join(documentation[-3:])
                for name in names:
                    if name.startswith(('.', '-')) or any(
                        c in name for c in '$%\\*?[]'
                    ):
                        continue
                    tasks.setdefault(
                        name,
                        entry('make', name, description, str(path.relative_to(root))),
                    )
            if text:
                documentation = []

    filename = next(
        (p for p in ['GNUmakefile', 'makefile', 'Makefile'] if local(root, p)), None
    )
    if filename:
        parse(filename)
    # Use the selected top-level makefile at execution time, not an included file.
    for task in tasks.values():
        task['file'] = filename
    return list(tasks.values())


def just_tasks(root):
    filename = next(
        (p for p in ['justfile', 'Justfile', '.justfile'] if local(root, p)), None
    )
    if not filename:
        return [], []
    executable = shutil.which('just')
    if not executable:
        return [], ['Install Just to inspect its recipes.']
    try:
        result = subprocess.run(
            [
                executable,
                '--justfile',
                str(root / filename),
                '--dump',
                '--dump-format',
                'json',
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        data = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return [], ['Could not parse the Justfile.']
    tasks = []

    def collect(module, prefix=''):
        if not isinstance(module, dict):
            return
        recipes = module.get('recipes', {})
        for name, recipe in recipes.items():
            if not isinstance(recipe, dict) or recipe.get('private'):
                continue
            parameters = ' '.join(
                p['name'] if p.get('default') is None else '[' + p['name'] + ']'
                for p in recipe.get('parameters', [])
                if isinstance(p, dict) and isinstance(p.get('name'), str)
            )
            task = entry(
                'just', prefix + name, recipe.get('doc') or '', filename, parameters
            )
            task['file'] = filename
            tasks.append(task)
        for name, alias in module.get('aliases', {}).items():
            if not isinstance(alias, dict) or 'private' in alias.get('attributes', []):
                continue
            if alias.get('target') in recipes and not recipes[alias['target']].get(
                'private'
            ):
                task = entry(
                    'just', prefix + name, 'Alias for ' + alias['target'], filename
                )
                task['file'] = filename
                tasks.append(task)
        for name, child in module.get('modules', {}).items():
            collect(child, prefix + name + '::')

    collect(data)
    return tasks, []


def discover(root, mise_tasks=()):
    root = Path(root)
    tasks = [
        entry('mise', t['name'], t['description'], t['source']) for t in mise_tasks
    ]
    data = package_data(root)
    manager = package_manager(root, data)
    scripts = data.get('scripts', {})
    if isinstance(scripts, dict):
        for name, command in scripts.items():
            if isinstance(command, str):
                tasks.append(
                    entry('package', name, command, 'package.json', tool=manager)
                )
    tasks.extend(make_tasks(root))
    recipes, notes = just_tasks(root)
    tasks.extend(recipes)
    tasks = [t for t in tasks if t['name'] and not t['name'].startswith('-')]
    return sorted(tasks, key=lambda t: (t['tool'].casefold(), t['name'])), notes


def command(root, runner, name, arguments=()):
    """Re-read declarations immediately before launching the selected native runner."""
    if runner not in ('package', 'make', 'just'):
        raise ValueError('Unknown task runner.')
    tasks, _ = discover(root)
    task = next((t for t in tasks if t['runner'] == runner and t['name'] == name), None)
    if not task:
        raise ValueError(
            'The selected task is no longer available. Refresh the overview.'
        )
    if runner == 'package':
        manager = package_manager(root, package_data(root))
        result = [manager, 'run', name]
        if manager == 'npm' and arguments:
            result.append('--')
    elif runner == 'make':
        result = ['make', '--file', str(root / task['file']), '--', name]
    else:
        result = ['just', '--justfile', str(root / task['file']), '--', name]
    return [*result, *arguments]
