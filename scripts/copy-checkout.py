"""Archinstall plugin: stage repository assets before custom commands execute."""

from pathlib import Path
import shutil
import json
import sys

__archinstall__version__ = 4.5


class Plugin:
    def on_mirrors(self, mirrors):
        source = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(source / 'scripts'))
        from repository_policy import configure_signature_policy

        raw = json.loads((source / 'user-configuration.json').read_text())
        return configure_signature_policy(mirrors, raw.get('extra', {}))

    def on_install(self, installation):
        source = Path(__file__).resolve().parents[1]
        destination = installation.target / 'root/system-configuration'
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(
                f'Checkout staging path already exists: {destination}'
            )
        shutil.copytree(
            source,
            destination,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                '__pycache__', '.agents', '.aws', '.codex', 'node_modules'
            ),
        )

        link = installation.target / 'run/system-configuration.json'
        link.parent.mkdir(parents=True, exist_ok=True)
        link.unlink(missing_ok=True)
        link.symlink_to('/root/system-configuration/user-configuration.json')

        # pacstrap -K creates a fresh target keyring. Prepare repository trust
        # before archinstall installs applications and explicit native packages.
        raw = json.loads((source / 'user-configuration.json').read_text())
        if raw.get('extra', {}).get('pre'):
            installation.arch_chroot(
                'CONFIG_MODE=install bash /root/system-configuration/scripts/configure.sh --pre'
            )
