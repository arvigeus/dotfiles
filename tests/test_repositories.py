import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

REPO = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name, REPO / 'scripts' / (name + '.py')
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryTests(unittest.TestCase):
    def test_native_signature_policy_keeps_packages_required(self):
        from archinstall.lib.models.mirrors import MirrorConfiguration

        fragment = json.loads(
            (REPO / 'modules/system/package/repositories/config.json').read_text()
        )
        mirrors = MirrorConfiguration.parse_args(fragment['mirror_config'])
        policy = load_script('repository_policy')
        policy.configure_signature_policy(mirrors, fragment['extra'])
        self.assertEqual(
            [repo.name for repo in mirrors.custom_repositories], ['ogc', 'chaotic-aur']
        )
        self.assertEqual(
            mirrors.repositories_config().count(
                'SigLevel = Required TrustedOnly DatabaseOptional'
            ),
            2,
        )
        before = mirrors.repositories_config()
        policy.configure_signature_policy(mirrors, fragment['extra'])
        self.assertEqual(mirrors.repositories_config(), before)

    def test_prepares_keys_before_bootstrap_packages_and_populates_keyring(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'calls'
            for name, failure in (('pacman-key', '--list-keys'), ('pacman', '-Q')):
                path = root / name
                path.write_text(
                    '#!/bin/sh\nprintf "%s %s\\n" "'
                    + name
                    + '" "$*" >> "$REPO_TEST_LOG"\n[ "$1" != "'
                    + failure
                    + '" ]\n'
                )
                path.chmod(0o755)
            subprocess.run(
                ['bash', str(REPO / 'modules/system/package/repositories/pre.sh')],
                check=True,
                env=dict(
                    os.environ,
                    PATH=str(root) + ':' + os.environ['PATH'],
                    REPO_TEST_LOG=str(log),
                ),
            )
            calls = log.read_text().splitlines()
            transaction = next(
                i for i, call in enumerate(calls) if call.startswith('pacman -U')
            )
            trust = [
                i
                for i, call in enumerate(calls)
                if call.startswith('pacman-key --lsign-key')
            ]
            self.assertEqual(len(trust), 2)
            self.assertTrue(all(index < transaction for index in trust))
            self.assertEqual(calls[-1], 'pacman-key --populate chaotic')

    def test_installer_pre_runs_in_target_before_later_package_operations(self):
        plugin = load_script('copy-checkout')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            (source / 'scripts').mkdir(parents=True)
            (source / 'user-configuration.json').write_text(
                json.dumps({'extra': {'pre': ['modules/repositories/pre.sh']}})
            )
            target = root / 'target'
            target.mkdir()
            commands = []
            from unittest.mock import patch

            with patch.object(
                plugin, '__file__', str(source / 'scripts/copy-checkout.py')
            ):
                plugin.Plugin().on_install(
                    SimpleNamespace(target=target, arch_chroot=commands.append)
                )
            self.assertEqual(
                commands,
                [
                    'CONFIG_MODE=install bash /root/system-configuration/scripts/configure.sh --pre'
                ],
            )
            self.assertTrue(
                (target / 'root/system-configuration/user-configuration.json').exists()
            )
