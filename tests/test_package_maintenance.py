"""Package maintenance hooks and Meld handoff with isolated commands."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import pty
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import tomllib

REPO = Path(__file__).resolve().parents[1]
PACMAN = REPO / 'modules/system/package/pacman'
MELD = REPO / 'modules/dev/tools/meld'
loader = importlib.machinery.SourceFileLoader(
    'orphan_report', str(PACMAN / 'files/usr/local/libexec/pacman-report-orphans')
)
spec = importlib.util.spec_from_loader(loader.name, loader)
report = importlib.util.module_from_spec(spec)
loader.exec_module(report)
maintenance_loader = importlib.machinery.SourceFileLoader(
    'package_maintenance',
    str(
        REPO / 'modules/system/package/topgrade/files/usr/local/bin/package-maintenance'
    ),
)
maintenance_spec = importlib.util.spec_from_loader(
    maintenance_loader.name, maintenance_loader
)
maintenance = importlib.util.module_from_spec(maintenance_spec)
maintenance_loader.exec_module(maintenance)


class PackageMaintenanceTests(unittest.TestCase):
    def run_report(self, code=0, stdout='', stderr='', error=None):
        output = io.StringIO()
        with (
            patch.object(
                report.subprocess,
                'run',
                return_value=SimpleNamespace(
                    returncode=code, stdout=stdout, stderr=stderr
                ),
                side_effect=error,
            ) as run,
            redirect_stdout(output),
            redirect_stderr(output),
        ):
            status = report.main()
        self.assertEqual(run.call_args.args[0], ['pacman', '-Qtdq'])
        return status, output.getvalue()

    def test_orphans_are_only_reported_and_empty_queries_are_normal(self):
        status, output = self.run_report(stdout='old-library\nold-tool\n')
        self.assertEqual(status, 0)
        self.assertIn('old-library', output)
        self.assertIn('nothing removed', output)
        self.assertIn('--asexplicit', output)
        self.assertEqual(self.run_report(code=1), (0, ''))

    def test_query_errors_and_timeout_are_never_reported_as_empty_success(self):
        status, output = self.run_report(code=1, stderr='database unavailable')
        self.assertEqual(status, 1)
        self.assertIn('database unavailable', output)
        status, output = self.run_report(error=subprocess.TimeoutExpired('pacman', 10))
        self.assertEqual(status, 1)
        self.assertIn('Could not check', output)

    def test_stale_service_hook_has_no_mutating_checkservices_defaults(self):
        source = (
            PACMAN / 'files/etc/pacman.d/hooks/99-report-stale-services.hook'
        ).read_text()
        self.assertIn('When = PostTransaction', source)
        self.assertNotIn('AbortOnFail', source)
        self.assertIn('Exec = /usr/local/libexec/pacman-report-services', source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            systemd = root / 'systemd'
            detect = root / 'detect'
            detect.write_text('#!/bin/sh\nexit "$CHROOT"\n')
            detect.chmod(0o755)
            timeout = root / 'timeout'
            timeout.write_text(
                '#!/usr/bin/python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n'
            )
            timeout.chmod(0o755)
            source = (
                PACMAN / 'files/usr/local/libexec/pacman-report-services'
            ).read_text()
            source = (
                source.replace('/run/systemd/system', str(systemd))
                .replace('/usr/bin/systemd-detect-virt', str(detect))
                .replace('/usr/bin/timeout', str(timeout))
            )
            wrapper = root / 'report'
            wrapper.write_text(source)
            for live, chroot in [(False, False), (True, True), (True, False)]:
                if live:
                    systemd.mkdir(exist_ok=True)
                result = subprocess.run(
                    ['/usr/bin/bash', str(wrapper)],
                    env=dict(os.environ, CHROOT='0' if chroot else '1'),
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                if live and not chroot:
                    self.assertEqual(
                        json.loads(result.stdout),
                        ['30s', '/usr/bin/checkservices', '-F', '-P', '-L', '-R'],
                    )
                else:
                    self.assertEqual(result.stdout, '')

    def run_pacnew(self, graphical, status=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'cache with spaces'
            other = root / 'other-cache'
            cache.mkdir()
            other.mkdir()
            old = 'example-1.0-1-any.pkg.tar.zst'
            (cache / old).write_text('old package')
            (cache / 'example-2.0-1-any.pkg.tar.zst').write_text('current package')
            (cache / (old + '.sig')).write_text('signature')
            (other / old).write_text('duplicate from lower-priority cache')
            private = cache / 'download-private'
            private.mkdir()
            (private / 'hidden-0.0-1-any.pkg.tar.zst').write_text('private download')
            private.chmod(0)
            config = root / 'pacman-conf'
            config.write_text(
                '#!/usr/bin/python3\nprint('
                + repr(str(cache))
                + ')\nprint('
                + repr(str(other))
                + ')\n'
            )
            config.chmod(0o755)
            path = root / 'pacdiff'
            path.write_text("""#!/usr/bin/python3
import json,os,sys,subprocess
from pathlib import Path
args=sys.argv[1:]
result=dict(editor=os.environ.get('DIFFPROG'),args=args)
if '--cachedir' in args:
 cache=Path(args[args.index('--cachedir')+1])
 result['archives']={path.name:path.read_text() for path in cache.iterdir()}
 scan=subprocess.run(['find',str(cache),'-name','*.pkg.tar*'],capture_output=True,text=True)
 result['find_errors']=scan.stderr
print(json.dumps(result))
raise SystemExit(int(os.environ['FAKE_PACDIFF_STATUS']))
""")
            path.chmod(0o755)
            script = (MELD / 'files/usr/local/bin/pacnew-review').read_text()
            # The test runner may be root; exercise the regular-user branch in
            # the isolated copy without elevating or launching any GUI.
            script = script.replace('(( EUID == 0 ))', 'false')
            wrapper = root / 'review'
            wrapper.write_text(script)
            env = dict(
                os.environ,
                PATH=str(root) + ':/usr/bin',
                WAYLAND_DISPLAY='test' if graphical else '',
                DISPLAY='',
                FAKE_PACDIFF_STATUS=str(status),
            )
            master, slave = pty.openpty()
            try:
                result = subprocess.run(
                    ['/usr/bin/bash', str(wrapper)],
                    stdin=slave if graphical else subprocess.DEVNULL,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(private.stat().st_mode & 0o777, 0)
            finally:
                os.close(master)
                os.close(slave)
                private.chmod(0o700)
            self.assertEqual(result.returncode, status, result.stderr)
            self.assertEqual(result.stderr, '')
            value = json.loads(result.stdout)
            if graphical:
                view = value['args'][value['args'].index('--cachedir') + 1]
                self.assertFalse(
                    Path(view).exists(), 'Temporary archive view survived exit'
                )
                self.assertEqual(
                    value['archives'],
                    {
                        old: 'old package',
                        'example-2.0-1-any.pkg.tar.zst': 'current package',
                    },
                )
                self.assertEqual(value['find_errors'], '')
                self.assertEqual((cache / old).read_text(), 'old package')
            return value

    def test_meld_runs_through_sudoedit_without_traversing_private_downloads(self):
        result = self.run_pacnew(True)
        self.assertEqual(result['editor'], 'meld')
        self.assertEqual(result['args'][:3], ['--sudo', '--backup', '--cachedir'])
        self.assertEqual(self.run_pacnew(False), dict(editor='meld', args=['--output']))

    def test_archive_view_is_cleaned_up_even_when_pacdiff_fails(self):
        self.run_pacnew(True, status=7)

    def test_topgrade_replaces_native_root_editor_without_enabling_cleanup(self):
        path = (
            REPO
            / 'modules/system/package/topgrade/files/home/.config/topgrade.d/maintenance.toml'
        )
        config = tomllib.loads(path.read_text())
        self.assertEqual(
            config['misc']['disable'], ['config_update', 'claude_code', 'pi']
        )
        self.assertEqual(
            config['commands']['Pi extensions'],
            'if command -v pi >/dev/null 2>&1; then pi update --extensions; fi',
        )
        self.assertFalse(config['misc']['cleanup'])
        self.assertTrue(config['linux']['show_arch_news'])
        self.assertNotIn('pre_commands', config)
        self.assertEqual(
            list(config['post_commands'].values()), ['package-maintenance']
        )


class InteractiveMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        stdout = redirect_stdout(self.output)
        stderr = redirect_stderr(self.output)
        stdout.__enter__()
        stderr.__enter__()
        self.addCleanup(stdout.__exit__, None, None, None)
        self.addCleanup(stderr.__exit__, None, None, None)

    def test_selection_supports_skip_all_deduplication_and_rejects_invalid_input(self):
        for answers, expected in [
            ([''], []),
            (['0'], ['one', 'two']),
            (['9', '2 2'], ['two']),
            (['1; reboot', '1'], ['one']),
        ]:
            with (
                self.subTest(answers=answers),
                patch('builtins.input', side_effect=answers),
            ):
                self.assertEqual(
                    maintenance.select_items('Select', ['one', 'two']), expected
                )
        with patch('builtins.input', side_effect=EOFError):
            self.assertEqual(maintenance.select_items('Select', ['one']), [])

    def test_orphan_removal_only_uses_selected_still_orphaned_packages(self):
        with (
            patch.object(
                maintenance,
                'orphan_packages',
                side_effect=[['keep', 'remove', 'wanted-now'], ['keep', 'remove']],
            ),
            patch('builtins.input', return_value='2 3'),
            patch.object(maintenance, 'run', return_value=0) as run,
        ):
            self.assertEqual(maintenance.review_orphans(), 0)
            run.assert_called_once_with(
                ['sudo', '--', 'pacman', '-Rns', '--', 'remove']
            )

    def test_declined_or_stale_selections_never_remove_packages(self):
        for answer in ('', '1'):
            with (
                patch.object(
                    maintenance, 'orphan_packages', side_effect=[['wanted-now'], []]
                ),
                patch('builtins.input', return_value=answer),
                patch.object(maintenance, 'run') as run,
            ):
                self.assertEqual(maintenance.review_orphans(), 0)
                run.assert_not_called()

    def test_failed_or_malformed_queries_never_offer_mutations(self):
        for code, stdout, stderr in [
            (1, '', 'database failed'),
            (0, '', 'partial read'),
            (0, '--unsafe\n', ''),
        ]:
            with (
                patch.object(
                    maintenance.subprocess,
                    'run',
                    return_value=SimpleNamespace(
                        returncode=code, stdout=stdout, stderr=stderr
                    ),
                ),
                patch('builtins.input') as prompt,
            ):
                with self.assertRaises((RuntimeError, ValueError)):
                    maintenance.review_orphans()
                prompt.assert_not_called()

    def test_service_review_only_restarts_selected_reported_non_session_units(self):
        output = """Services with broken maps files
'sddm.service'
'systemd-logind.service'
'dbus.service'
'user@1000.service'
'getty@tty1.service'
'one.service'
'two.service'
'--unsafe.service'
systemctl restart 'not-a-candidate.service'
"""
        with (
            patch.object(maintenance.Path, 'is_dir', return_value=True),
            patch.object(maintenance, 'query', return_value=output) as query,
            patch('builtins.input', side_effect=['9', '2']),
            patch.object(maintenance, 'run', return_value=0) as run,
        ):
            self.assertEqual(maintenance.review_services(), 0)
            query.assert_called_once_with(
                ['sudo', '--', '/usr/local/libexec/pacman-report-services'], timeout=60
            )
            run.assert_called_once_with(
                ['sudo', '--', 'systemctl', 'try-restart', '--', 'two.service']
            )

    def test_service_failures_are_reported_and_other_selected_units_still_run(self):
        with (
            patch.object(maintenance.Path, 'is_dir', return_value=True),
            patch.object(
                maintenance,
                'query',
                return_value="'one.service'\n'one.service'\n'other.service'\n",
            ),
            patch('builtins.input', return_value='0'),
            patch.object(maintenance, 'run', side_effect=[1, 0]) as run,
        ):
            self.assertEqual(maintenance.review_services(), 1)
            self.assertEqual(run.call_count, 2)
            self.assertIn('Could not restart one.service', self.output.getvalue())

    def test_main_reviews_configs_before_services_and_keeps_failure_status(self):
        order = []
        with (
            patch.object(maintenance.os, 'geteuid', return_value=1000),
            patch.object(maintenance.sys.stdin, 'isatty', return_value=True),
            patch.object(
                maintenance,
                'review_orphans',
                side_effect=lambda: order.append('orphans') or 1,
            ),
            patch.object(
                maintenance, 'run', side_effect=lambda argv: order.append(argv[0]) or 0
            ),
            patch.object(
                maintenance,
                'review_services',
                side_effect=lambda: order.append('services') or 0,
            ),
        ):
            self.assertEqual(maintenance.main(), 1)
            self.assertEqual(order, ['orphans', 'pacnew-review', 'services'])

    def test_config_failure_prevents_service_restart_review(self):
        with (
            patch.object(maintenance.os, 'geteuid', return_value=1000),
            patch.object(maintenance.sys.stdin, 'isatty', return_value=True),
            patch.object(maintenance, 'review_orphans', return_value=0),
            patch.object(maintenance, 'run', return_value=1),
            patch.object(maintenance, 'review_services') as services,
        ):
            self.assertEqual(maintenance.main(), 1)
            services.assert_not_called()

    def test_unattended_runs_report_without_sudo_or_mutations(self):
        with (
            patch.object(maintenance.os, 'geteuid', return_value=1000),
            patch.object(maintenance.sys.stdin, 'isatty', return_value=False),
            patch.object(maintenance, 'run', return_value=0) as run,
            patch.object(maintenance, 'review_services') as services,
            patch.object(maintenance, 'review_orphans') as orphans,
        ):
            self.assertEqual(maintenance.main(), 0)
            self.assertEqual(
                [entry.args[0] for entry in run.call_args_list],
                [['/usr/local/libexec/pacman-report-orphans'], ['pacnew-review']],
            )
            services.assert_not_called()
            orphans.assert_not_called()
