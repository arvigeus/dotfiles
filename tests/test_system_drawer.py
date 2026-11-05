"""System overview parsing and interactive actions; never updates the host."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

import support

SPEC = importlib.util.spec_from_file_location(
    'desktop_system', support.DESKTOP / 'drawers/system/backend.py'
)
backend = importlib.util.module_from_spec(SPEC)
_bytecode_disabled = sys.dont_write_bytecode
sys.dont_write_bytecode = True
SPEC.loader.exec_module(backend)
sys.dont_write_bytecode = _bytecode_disabled


def snapshot():
    return dict(
        os='Arch Linux',
        kernel='test-kernel',
        uptime=90061,
        kernelChanged=True,
        boot=dict(
            total='22.5s',
            phases=[
                dict(label='Kernel', duration='2.5s'),
                dict(label='Userspace', duration='20s'),
            ],
        ),
        slow=[dict(unit='slow.service', duration='10s')],
        scopes=[
            dict(
                scope='system',
                failed=[dict(unit='broken.service', description='Test failure')],
            ),
            dict(scope='user', failed=[]),
        ],
        timers=[dict(unit='cleanup.timer', scope='user', next=1792491033949)],
        errors={},
        terminalAvailable=True,
    )


class SystemBackendTests(unittest.TestCase):
    def setUp(self):
        self.output = self.enterContext(redirect_stdout(io.StringIO()))

    def test_snapshots_only_read_the_requested_section(self):
        with (
            patch.object(backend, 'command', return_value='[]') as run,
            patch.object(
                backend, 'system_info', return_value=dict(kernel='test')
            ) as info,
            patch.object(
                backend, 'maintenance_available', return_value=dict(health=True)
            ) as maintenance,
            patch.object(backend, 'updater') as update,
        ):
            boot = backend.snapshot('boot')
            self.assertEqual(
                [entry.args[0][0] for entry in run.call_args_list],
                ['systemd-analyze'] * 2,
            )
            self.assertNotIn('scopes', boot)
            info.assert_not_called()
            maintenance.assert_not_called()
            run.reset_mock()
            services = backend.snapshot('services')
            self.assertEqual(
                [entry.args[0][0] for entry in run.call_args_list], ['systemctl'] * 4
            )
            self.assertNotIn('boot', services)
            run.reset_mock()
            self.assertEqual(backend.snapshot('info')['kernel'], 'test')
            info.assert_called_once()
            maintenance.assert_not_called()
            run.assert_not_called()
            update.assert_not_called()

    def test_boot_phases_handle_optional_initrd_and_minute_units(self):
        result = backend.boot_times(
            'Startup finished in 9s (firmware) + 500ms (loader) + 2s (kernel) + 1min 2.4s (initrd) + 3s (userspace) = 1min 16.9s\ngraphical.target reached after 3s in userspace.'
        )
        self.assertEqual(result['total'], '1min 16.9s')
        self.assertEqual(
            result['phases'][3], dict(label='Initrd', duration='1min 2.4s')
        )
        self.assertEqual(backend.boot_times('')['phases'], [])
        self.assertEqual(
            backend.slow_units(' 1min 5s slow.service\n 100ms fast.service')[0],
            dict(duration='1min 5s', unit='slow.service'),
        )

    def test_partial_errors_do_not_report_healthy_services_and_timer_units_are_ms(self):
        def command(argv):
            if argv[0] == 'systemd-analyze':
                raise RuntimeError('Boot still in progress')
            if '--user' in argv and 'list-units' in argv:
                raise RuntimeError('User bus unavailable')
            if 'list-units' in argv:
                return json.dumps(
                    [dict(unit='bad.service', description='Failed service')]
                )
            return json.dumps(
                [
                    dict(unit='late.timer', next=1792491133949065),
                    dict(unit='unset.timer', next=2**64 - 1),
                    dict(unit='soon.timer', next=1792491033949065),
                ]
            )

        with patch.object(backend, 'command', side_effect=command):
            boot = backend.snapshot('boot')
            state = backend.snapshot('services')
        self.assertEqual(state['scopes'][0]['failed'][0]['unit'], 'bad.service')
        self.assertIn('user', state['errors'])
        self.assertIn('boot', boot['errors'])
        self.assertEqual(state['timers'][0]['next'], 1792491033949.065)
        self.assertNotIn('unset.timer', [row['unit'] for row in state['timers']])

    def test_updates_are_interactive_and_journal_unit_is_literal(self):
        with patch.object(
            backend.shutil,
            'which',
            side_effect=lambda name: (
                name if name in ('system-update', 'topgrade') else None
            ),
        ):
            self.assertEqual(backend.action_command('update'), ['system-update'])
        with patch.object(
            backend.shutil,
            'which',
            side_effect=lambda name: (
                name if name in ('topgrade', 'paru', 'sudo', 'pacman') else None
            ),
        ):
            self.assertEqual(backend.action_command('update'), ['topgrade'])
        with patch.object(
            backend.shutil,
            'which',
            side_effect=lambda name: name if name in ('sudo', 'pacman') else None,
        ):
            with self.assertRaisesRegex(ValueError, 'Topgrade'):
                backend.action_command('update')
        self.assertEqual(
            backend.action_command('logs', 'user', r'foo\x2dbar.service'),
            ['journalctl', '--user', '-b', '-n', '200', r'--unit=foo\x2dbar.service'],
        )
        for unit in ('--system', '$(touch /tmp/unsafe)', 'foo;bar'):
            with self.assertRaises(ValueError):
                backend.action_command('logs', 'system', unit)
        with self.assertRaises(ValueError):
            backend.action_command('restart')

    def test_signing_repair_preserves_keyring_and_stops_on_failure(self):
        with (
            patch.object(
                backend, 'maintenance_available', return_value=dict(signing=True)
            ),
            patch.object(
                backend, 'run_terminal', return_value=SimpleNamespace(returncode=0)
            ) as run,
            patch('builtins.input', return_value='y'),
        ):
            self.assertEqual(backend.run_action('repair-signing'), 0)
            self.assertEqual(
                run.call_args_list,
                [
                    call(['sudo', '--', 'pacman-key', op])
                    for op in ('--init', '--populate', '--updatedb')
                ],
            )
            run.reset_mock()
            run.side_effect = [
                SimpleNamespace(returncode=0),
                SimpleNamespace(returncode=2),
            ]
            self.assertEqual(backend.run_action('repair-signing'), 2)
            self.assertEqual(run.call_count, 2)

    def test_signing_repair_needs_explicit_confirmation(self):
        # Passwordless sudo gives no prompt of its own, so declining, an empty
        # answer and a closed stdin must all leave the keyring untouched.
        for answer in ('n', '', 'yes please', EOFError()):
            with (
                self.subTest(answer=answer),
                patch.object(
                    backend, 'maintenance_available', return_value=dict(signing=True)
                ),
                patch.object(backend, 'run_terminal') as run,
                patch('builtins.input', side_effect=[answer]) as prompt,
            ):
                self.assertEqual(backend.run_action('repair-signing'), 0)
                prompt.assert_called_once()
                run.assert_not_called()
        self.assertIn('Nothing changed.', self.output.getvalue())

    def test_interactive_commands_keep_the_user_locale(self):
        with patch.object(backend.subprocess, 'run') as run:
            backend.run_terminal(['journalctl', '-b'])
        # No env override: LC_ALL=C made the journal pager escape non-ASCII text.
        self.assertNotIn('env', run.call_args.kwargs)

    def test_unavailable_maintenance_never_launches_commands(self):
        with (
            patch.object(
                backend,
                'maintenance_available',
                return_value=dict(signing=False, health=False),
            ),
            patch.object(backend, 'run_terminal') as run,
        ):
            for action in ('repair-signing', 'check-packages', 'unknown'):
                with self.assertRaises(ValueError):
                    backend.run_action(action)
            run.assert_not_called()

    def test_health_checks_both_scopes_without_changes_when_repair_declined(self):
        with (
            patch.object(
                backend, 'maintenance_available', return_value=dict(health=True)
            ),
            patch.object(
                backend,
                'run_terminal',
                side_effect=[
                    SimpleNamespace(returncode=1),
                    SimpleNamespace(
                        returncode=1,
                        stdout='broken /usr/bin/missing\n',
                        stderr='missing file\n',
                    ),
                ],
            ) as run,
            patch.object(backend, 'command', return_value='broken\n'),
            patch.object(backend.shutil, 'which', return_value='/usr/bin/sudo'),
            patch('builtins.input', return_value='n'),
        ):
            self.assertEqual(backend.run_action('check-packages'), 1)
            self.assertEqual(
                [args.args[0] for args in run.call_args_list],
                [['pacman', '-Dk'], ['pacman', '-Qkq']],
            )

    def test_health_repair_targets_only_reported_repository_packages_and_rechecks(self):
        with (
            patch.object(
                backend, 'maintenance_available', return_value=dict(health=True)
            ),
            patch.object(
                backend,
                'run_terminal',
                side_effect=[
                    SimpleNamespace(returncode=0),
                    SimpleNamespace(
                        returncode=1,
                        stdout='broken /usr/bin/missing\nbroken /usr/lib/missing\nforeign /opt/missing\n--unsafe /missing\n$(touch /missing\n',
                        stderr='',
                    ),
                    SimpleNamespace(returncode=0),
                    SimpleNamespace(returncode=0),
                    SimpleNamespace(returncode=0, stdout='', stderr=''),
                ],
            ) as run,
            patch.object(
                backend, 'command', return_value='broken\nhealthy\n--unsafe\n'
            ),
            patch.object(backend.shutil, 'which', return_value='/usr/bin/sudo'),
            patch('builtins.input', return_value='yes') as prompt,
        ):
            self.assertEqual(backend.run_action('check-packages'), 0)
            self.assertEqual(
                run.call_args_list[2],
                call(['sudo', '--', 'pacman', '-Syu', '--', 'broken']),
            )
            self.assertEqual(run.call_count, 5)
            prompt.assert_called_once()

    def test_healthy_packages_and_unreadable_repository_list_offer_no_repair(self):
        with (
            patch.object(
                backend, 'maintenance_available', return_value=dict(health=True)
            ),
            patch.object(
                backend,
                'run_terminal',
                side_effect=[
                    SimpleNamespace(returncode=0),
                    SimpleNamespace(returncode=0, stdout='', stderr=''),
                    SimpleNamespace(returncode=0),
                    SimpleNamespace(
                        returncode=1, stdout='broken /missing\n', stderr=''
                    ),
                ],
            ) as run,
            patch.object(backend, 'command', side_effect=RuntimeError('Unavailable')),
            patch('builtins.input') as prompt,
        ):
            self.assertEqual(backend.check_package_health(), 0)
            self.assertEqual(backend.check_package_health(), 1)
            self.assertEqual(run.call_count, 4)
            prompt.assert_not_called()

    def locked_tree(self):
        """Return (absent path, path in a directory the test user cannot search)."""
        if os.geteuid() == 0:
            self.skipTest('root can read every directory')
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        locked = root / 'locked'
        locked.mkdir()
        (locked / 'present').write_text('')
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o700)
        return root / 'absent', locked / 'present'

    def test_unreadable_files_are_unchecked_not_missing(self):
        # Unprivileged pacman -Qkq lists files under /boot (0700) or /var/named
        # as missing. Repairing those would rewrite boot images and still fail.
        absent, unreadable = self.locked_tree()
        self.assertEqual(
            backend.missing_files(
                f'kept {absent}\nboot {unreadable}\n--flag /x\nnot a pair\n'
            ),
            (
                [('kept', str(absent))],
                [('boot', str(unreadable))],
                ['--flag /x', 'not a pair'],
            ),
        )

        def checks(files):
            return [SimpleNamespace(returncode=0), files]

        with (
            patch.object(
                backend, 'maintenance_available', return_value=dict(health=True)
            ),
            patch.object(backend, 'run_terminal') as run,
            patch.object(backend, 'command', return_value='kept\nboot\n') as native,
            patch.object(backend.shutil, 'which', return_value='/usr/bin/sudo'),
            patch('builtins.input', return_value='n') as prompt,
        ):
            run.side_effect = checks(
                SimpleNamespace(returncode=1, stdout=f'boot {unreadable}\n', stderr='')
            )
            self.assertEqual(backend.check_package_health(), 0)
            native.assert_not_called()
            self.assertEqual(run.call_count, 2, 'declined root check still ran')
            prompt.assert_called_once()
            self.assertIn('as root?', prompt.call_args.args[0])
            self.assertIn(
                'Check them with: sudo pacman -Qk boot', self.output.getvalue()
            )
            self.assertIn('No database inconsistencies', self.output.getvalue())
            prompt.reset_mock()

            # Only the genuinely missing file becomes a repair target.
            run.side_effect = checks(
                SimpleNamespace(
                    returncode=1,
                    stdout=f'boot {unreadable}\nkept {absent}\n',
                    stderr='',
                )
            )
            self.assertEqual(backend.check_package_health(), 1)
            self.assertIn(
                'Repository packages with missing files: kept\n', self.output.getvalue()
            )
            self.assertEqual(prompt.call_count, 2)

            # A failure with nothing to explain it, or with diagnostics, still fails.
            for stdout, stderr in (('', ''), (f'boot {unreadable}\n', 'error: x\n')):
                run.side_effect = checks(
                    SimpleNamespace(returncode=1, stdout=stdout, stderr=stderr)
                )
                self.assertEqual(backend.check_package_health(offer_repair=False), 1)
            run.side_effect = [
                SimpleNamespace(returncode=1),
                SimpleNamespace(returncode=1, stdout=f'boot {unreadable}\n', stderr=''),
            ]
            self.assertEqual(backend.check_package_health(), 1)

    def test_root_check_is_opt_in_read_only_and_reused_after_repair(self):
        _, unreadable = self.locked_tree()
        user = SimpleNamespace(returncode=1, stdout=f'boot {unreadable}\n', stderr='')
        lost = SimpleNamespace(returncode=1, stdout='boot /boot/ucode.img\n', stderr='')
        clean = SimpleNamespace(returncode=0, stdout='', stderr='')
        ok = SimpleNamespace(returncode=0)
        root = call(
            ['sudo', '--', 'pacman', '-Qkq', '--', 'boot'],
            capture_output=True,
            text=True,
        )
        with (
            patch.object(
                backend, 'maintenance_available', return_value=dict(health=True)
            ),
            patch.object(backend, 'run_terminal') as run,
            patch.object(backend, 'command', return_value='boot\n'),
            patch.object(backend.shutil, 'which', return_value='/usr/bin/sudo'),
            patch('builtins.input') as prompt,
        ):
            # Root sees every file: the unverified one is present.
            run.side_effect, prompt.side_effect = [ok, user, clean], ['y']
            self.assertEqual(backend.check_package_health(), 0)
            self.assertEqual(run.call_args_list[2], root)
            self.assertNotIn('Check them with', self.output.getvalue())

            # Root reports it missing: it becomes a repair target.
            run.reset_mock()
            run.side_effect, prompt.side_effect = [ok, user, lost], ['y', 'n']
            self.assertEqual(backend.check_package_health(), 1)
            self.assertIn(
                'Missing package files:\n  boot /boot/ucode.img\n',
                self.output.getvalue(),
            )
            self.assertEqual(run.call_count, 3)

            # Root diagnostics are a failure, never targets.
            run.reset_mock()
            failed = SimpleNamespace(returncode=1, stdout='', stderr='error: x\n')
            run.side_effect, prompt.side_effect = [ok, user, failed], ['y']
            self.assertEqual(backend.check_package_health(), 1)
            self.assertEqual(run.call_count, 3)

            # After an accepted repair the recheck reuses the root decision.
            run.reset_mock()
            prompt.reset_mock()
            run.side_effect = [ok, user, lost, ok, ok, user, clean]
            prompt.side_effect = ['y', 'y']
            self.assertEqual(backend.check_package_health(), 0)
            self.assertEqual(
                run.call_args_list[3],
                call(['sudo', '--', 'pacman', '-Syu', '--', 'boot']),
            )
            self.assertEqual(run.call_args_list[6], root)
            self.assertEqual(prompt.call_count, 2)

    def test_health_cli_retains_exit_status_and_only_runs_stub_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pacman = folder / 'pacman'
            pacman.write_text(
                f'#!{sys.executable}\n'
                + """import os,sys
from pathlib import Path
with Path(os.environ['COMMAND_LOG']).open('a') as log: log.write(' '.join(sys.argv[1:])+'\\n')
if os.environ['BROKEN'] == '1':
 if sys.argv[1:] == ['-Qkq']: print('broken /usr/bin/missing'); sys.exit(1)
 if sys.argv[1:] == ['-Qnq']: print('broken')
if os.environ['BROKEN'] == 'locked' and sys.argv[1:] == ['-Qkq']:
 print('amd-ucode', os.environ['LOCKED']); sys.exit(1)
"""
            )
            pacman.chmod(0o755)
            # Sudo exists, but may only run the read-only root file check.
            sudo = folder / 'sudo'
            sudo.write_text(
                f'#!{sys.executable}\n'
                + """import os,sys
args = sys.argv[1:]
if args[:3] != ['--', 'pacman', '-Qkq'] or args[3:4] != ['--']:
 raise RuntimeError('Unexpected mutation')
os.execvp(args[1], args[1:])
"""
            )
            sudo.chmod(0o755)
            locked = folder / 'boot'
            locked.mkdir()
            (locked / 'amd-ucode.img').write_text('')
            locked.chmod(0)  # TemporaryDirectory restores access to clean up.
            cases = [
                ('0', 'n', 0, ['-Dk', '-Qkq']),
                ('1', 'n', 1, ['-Dk', '-Qkq', '-Qnq']),
            ]
            if os.geteuid():
                cases += [
                    ('locked', 'n', 0, ['-Dk', '-Qkq']),
                    ('locked', 'y', 0, ['-Dk', '-Qkq', '-Qkq -- amd-ucode']),
                ]
            for broken, answer, expected, commands in cases:
                log = folder / 'commands'
                log.write_text('')
                result = subprocess.run(
                    [sys.executable, str(SPEC.origin), '--action', 'check-packages'],
                    env=dict(
                        os.environ,
                        PATH=str(folder),
                        COMMAND_LOG=str(log),
                        BROKEN=broken,
                        LOCKED=str(locked / 'amd-ucode.img'),
                    ),
                    input=answer + '\n\n',
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                self.assertEqual(
                    result.returncode, expected, result.stdout + result.stderr
                )
                self.assertIn(f'Finished (exit {expected})', result.stdout)
                self.assertEqual(log.read_text().splitlines(), commands)
                if broken == 'locked':
                    self.assertNotIn('Reinstall', result.stdout)
                    self.assertEqual(
                        'Check them with: sudo pacman -Qk amd-ucode' in result.stdout,
                        answer == 'n',
                    )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class SystemDrawerTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_full_width_actions_popovers_info_and_narrow_layout(self):
        state = json.dumps(snapshot())
        self.run_qml(
            """import QtQuick
import QtQuick.Layouts
import QtTest
import Quickshell
import "ui"
import "drawers"
ShellRoot {
 id: root
 property var calls: []
 QtObject { id: mock; property var state: STATE; property bool loaded:true; property bool busy:false; property string error:""; function refresh(){} function openTerminal(action,scope,unit){root.calls.push([action,scope,unit]);} }
 FloatingWindow { id: window; implicitWidth:480; implicitHeight:1000; visible:true; color:Theme.background
  Rectangle { id: preview; width:page.width+32;height:1000;color:Theme.background
   Loader { id: header; x:preview.width-width-16;y:12;sourceComponent:page.headerActions }
   SystemDrawer { id: page; x:16;y:64;width:448;height:preview.height-80;active:true;service:mock }
  }
 }
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 function capture(name,item,next){
  const path=Quickshell.env("DISPLAY_PREVIEW_DIR");
  if(path)item.grabToImage(result=>{result.saveToFile(path+"/"+name+".png");next();});else next();
 }
 property int stage:0
 Timer { interval:180;repeat:true;running:true;onTriggered:{try{
  if(stage===0){
   for(const name of ["systemUpdate","systemBoot","systemServices","systemRepairSigning","systemCheckPackages"])
    check(Math.abs(find(page,name).width-page.width)<2,"action not full width: "+name);
   check(!find(page,"systemMaintenance")&&!find(page,"systemCleanup")&&!find(page,"systemScroll")&&!find(page,"systemInfoCard"),"duplicate drawer content remains");
   check(header.item.objectName==="systemInfo","information header missing");
   find(page,"systemUpdate").clicked();check(root.calls[0][0]==="update","update not explicit");capture("system-overview",preview,()=>find(page,"systemBoot").clicked());
  }else if(stage===1){
   check(page.bootPopover.visible&&page.escapeHandler,"boot popover did not open");
   check(Math.abs(page.bootPopover.width-page.width)<2,"boot popover squeezed");capture("system-boot",page.bootPopover.contentItem,()=>find(page,"systemServices").clicked());
  }else if(stage===2){
   check(page.servicesPopover.visible&&!page.bootPopover.visible,"popovers not exclusive");
   const empty=find(page.servicesPopover.contentItem,"systemTimersEmpty"),saved=mock.state;
   check(empty&&!empty.visible,"empty timer note shown beside timers");
   mock.state=Object.assign({},saved,{timers:[],errors:{userTimers:"User bus unavailable"}});
   check(!empty.visible,"failed timer read reported as no timers");
   mock.state=Object.assign({},saved,{timers:[]});
   check(empty.visible,"empty timer note missing");
   mock.state=saved;
   page.logs("user","broken.service");check(root.calls[1].join("|")==="logs|user|broken.service","log scope lost");capture("system-services",page.servicesPopover.contentItem,()=>header.item.clicked());
  }else if(stage===3){
   check(!page.servicesPopover.visible&&page.informationPopup?.visible&&page.escapeHandler,"information popup not exclusive");
   check(find(page.informationPopup.contentItem,"systemInfoCard").title==="Arch Linux","system information missing");
   capture("system-info",page.informationPopup.contentItem,()=>{
    page.escapeHandler();page.width=288;window.implicitWidth=320;
   });
  }else if(stage===4){
   for(const name of ["systemUpdate","systemBoot","systemServices","systemRepairSigning","systemCheckPackages"])
    check(Math.abs(find(page,name).width-page.width)<2,"narrow action not full width: "+name);
   capture("system-narrow",preview,()=>find(page,"systemServices").clicked());
  }else if(stage===5){
   check(page.servicesPopover.visible&&page.servicesPopover.width<=page.width,"narrow services popover overflow");capture("system-services-narrow",page.servicesPopover.contentItem,()=>page.escapeHandler());
  }else if(stage===6){
   check(!page.servicesPopover.visible&&!page.escapeHandler,"escape did not close popover");
   find(page,"systemBoot").clicked();find(page,"systemBoot").clicked();
   check(!page.bootPopover.visible,"boot toggle did not close");
   header.item.clicked();find(page,"systemRepairSigning").clicked();
   check(root.calls[2][0]==="repair-signing"&&!page.informationPopup,"direct signing action lost");
  }else if(stage===7){
   find(page,"systemBoot").clicked();find(page,"systemCheckPackages").clicked();
   check(root.calls[3][0]==="check-packages"&&!page.bootPopover.visible&&!page.requestedSection,"direct health action lost");
   mock.state=Object.assign({},mock.state,{terminalAvailable:false});
   check(find(page,"systemRepairSigning").enabled&&find(page,"systemCheckPackages").enabled,"direct actions depend on a preload");
   page.active=false;
   for(const name of ["systemUpdate","systemRepairSigning","systemCheckPackages"])
    check(!find(page,name).enabled,"inactive action enabled: "+name);
   check(!page.servicesPopover.visible&&!page.bootPopover.visible&&!page.informationPopup,"popover survived dismissal");
   page.active=true;header.item.clicked();page.active=false;
   check(!page.informationPopup,"information survived dismissal");
   console.log("DISPLAY_PASS");Qt.quit();return;
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",stage,e.message);Qt.quit();}}}
}
""".replace('STATE', state)
        )

    def test_service_reads_only_while_active_and_launches_literal_arguments(self):
        state = snapshot()

        def setup(root):
            (root / 'drawers/system/backend.py').write_text(
                'import json,time,sys\ntime.sleep(.05)\nstate='
                + repr(state)
                + '\nstate["kernel"]=sys.argv[-1]\nprint(json.dumps(state))\n'
            )

        self.run_qml(
            """import QtQuick
import Quickshell
import "drawers/system"
ShellRoot {
 id: root
 property var calls: []
 SystemService { id: service; launch: argv => root.calls.push(argv) }
 function check(value,message){if(!value)throw new Error(message);}
 property int stage:0
 Timer{interval:200;repeat:true;running:true;onTriggered:{try{
  if(stage===0){check(!service.busy&&!service.loaded,"eager observation");service.active=true;service.refresh();}
  else if(stage===1){
   check(!service.busy&&!service.loaded,"drawer activation preloaded information");
   service.openTerminal("repair-signing");service.openTerminal("check-packages");
   check(root.calls[0][4]==="repair-signing"&&root.calls[1][4]==="check-packages"&&!service.busy,"direct actions need preloading");
   root.calls=[];service.section="info";
  }else if(stage===2){
   check(service.loaded&&service.state.kernel==="info","backend snapshot missing: "+service.error);
   service.openTerminal("logs","user","foo\\x2dbar.service");
   const call=root.calls[0];check(call[0]==="xdg-terminal-exec"&&call[1]==="python3"&&call.slice(-4).join("|")==="--scope|user|--unit|foo\\x2dbar.service","terminal arguments changed");
   service.openTerminal("repair-signing");service.openTerminal("check-packages");
   check(root.calls[1][4]==="repair-signing"&&root.calls[2][4]==="check-packages","maintenance handoff lost");
   service.openTerminal("unknown");
   check(root.calls.length===3,"unknown action launched");
   service.section="services";service.section="";service.section="boot";
  }else if(stage===3){
   check(service.loaded&&!service.busy&&service.state.kernel==="boot","popup switch did not settle");
   service.refresh();service.section="";service.section="info";
  }else if(stage===4){
   check(service.loaded&&!service.busy&&service.state.kernel==="info","reopened popup retained a cancelled read");
   service.section="services";service.active=false;
  }else if(stage===5){check(!service.busy,"inactive worker running");console.log("DISPLAY_PASS");Qt.quit();return;}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",stage,e.message);Qt.quit();}}}
}
""",
            setup,
        )

    def test_service_releases_a_read_whose_helper_cannot_start(self):
        # Quickshell emits no exited signal when python3 cannot be started.
        with tempfile.TemporaryDirectory() as empty, patch.dict(os.environ, PATH=empty):
            self.run_qml(
                """import QtQuick
import Quickshell
import "drawers/system"
ShellRoot {
 SystemService { id: service; section: "info" }
 function check(value,message){if(!value)throw new Error(message);}
 property int stage:0
 Timer{interval:200;repeat:true;running:true;onTriggered:{try{
  if(stage===0)service.active=true;
  else if(stage===1){
   check(!service.busy&&!service.loaded&&service.error!=="","failed start left the read pending");
   service.refresh();
  }else if(stage===2){
   check(!service.busy&&service.error!=="","retry after a failed start did not settle");
   console.log("DISPLAY_PASS");Qt.quit();return;
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",stage,e.message);Qt.quit();}}}
}
"""
            )
