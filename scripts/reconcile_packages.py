"""Use libalpm's installed dependency graph; pacman owns every transaction."""
from pathlib import Path
import os
import subprocess

from reconcile import Review


class Inventory:
    def __init__(self, handle=None):
        import pyalpm
        if handle is None:
            from pycman.config import PacmanConfig
            handle = PacmanConfig('/etc/pacman.conf').initialize_alpm()
        self.handle = handle
        self.packages = handle.get_localdb().pkgcache
        self.by_name = {package.name: package for package in self.packages}
        self.satisfier = lambda name: pyalpm.find_satisfier(self.packages, name.split('/')[-1])

    def status(self, declared, aur=()):
        missing = []
        roots = []
        for name in dict.fromkeys(declared):
            package = self.satisfier(name)
            if package is None:
                missing.append(name)
            else:
                roots.append(package)
        for name in aur:
            package = self.by_name.get(name) or self.satisfier(name)
            if package is None:
                missing.append(name + ' (AUR)')
            else:
                roots.append(package)
        # An old kernel may still be running after a change to the declared set.
        running = Path('/usr/lib/modules') / os.uname().release / 'pkgbase'
        if running.is_file():
            package = self.by_name.get(running.read_text().strip())
            if package is not None:
                roots.append(package)
        protected = set()
        while roots:
            package = roots.pop()
            if package.name in protected:
                continue
            protected.add(package.name)
            for dependency in package.depends:
                found = self.satisfier(dependency)
                if found is None:
                    raise ValueError(f'Broken installed dependency: {package.name} requires {dependency}')
                roots.append(found)
        candidates = []
        for package in self.packages:
            if package.name in protected:
                continue
            if package.reason == 0 or (not package.compute_requiredby() and not package.compute_optionalfor()):
                candidates.append(package)
        return missing, sorted(candidates, key=lambda package: package.name)


def review_removals(declared, aur, review=None, inventory=Inventory, run=subprocess.run):
    if review is None:
        try:
            with open('/dev/tty', 'r+'):
                pass
        except OSError:
            print('Package removals skipped: no terminal. Run apply interactively to review them.')
            return
        review = Review()
    missing, candidates = inventory().status(declared, aur)
    if missing:
        raise ValueError('Declared packages are still missing; refusing removals: ' + ', '.join(missing))
    if not candidates:
        print('No extra explicit packages or orphan dependencies.')
        return
    print(f'{len(candidates)} extra explicit packages/orphan dependencies. Dependencies of declared packages are protected.')
    for candidate in candidates:
        # Re-read after each transaction: providers, dependencies and reasons can change.
        missing, current = inventory().status(declared, aur)
        if missing:
            raise ValueError('Package state changed; rerun apply before reviewing removals.')
        package = next((package for package in current if package.name == candidate.name), None)
        if package is None:
            continue
        details = (f'{package.name} {package.version} ({package.isize / 1024**2:.1f} MiB)\n'
                   f'  {package.desc}\n  Required by: {", ".join(package.compute_requiredby()) or "none"}'
                   f'\n  Optional for: {", ".join(package.compute_optionalfor()) or "none"}')
        choice = review.choose(details, {'r': 'remove this package', 'k': 'keep', 'q': 'finish review'}, 'k')
        if choice == 'q':
            break
        if choice == 'r':
            # No recursive removal, cascading or --nodeps; preserve pacsave behavior.
            result = run(['pacman', '-R', '--noconfirm', '--', package.name], check=False)
            if result.returncode:
                print(f'Not removed: {package.name}. Pacman refused the transaction; continuing review.')
