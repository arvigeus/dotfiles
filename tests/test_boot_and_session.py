import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
UUID = '244dbaa5-7415-460d-9354-ae5e2bd9333d'


class BootTests(unittest.TestCase):
    def run_hook(self, root, parameters, preset='default_uki="/boot/EFI/Linux/arch-linux.efi"\n'):
        cmdline = root / 'cmdline'
        cmdline.write_text(parameters)
        presets = root / 'presets'
        presets.mkdir(exist_ok=True)
        (presets / 'linux.preset').write_text(preset)
        config = root / 'config.json'
        config.write_text(json.dumps({'bootloader_config': {'bootloader': 'Efistub', 'uki': True}}))
        binary = root / 'bin'
        binary.mkdir(exist_ok=True)
        rebuild = binary / 'mkinitcpio'
        rebuild.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$BOOT_TEST_LOG"\n')
        rebuild.chmod(0o755)
        script = (REPO / 'modules/system/boot/scripts/90_boot.sh').read_text()
        script = script.replace('/run/system-configuration.json', str(config))
        script = script.replace('/etc/kernel/cmdline', str(cmdline)).replace('/etc/mkinitcpio.d', str(presets))
        result = subprocess.run(['bash', '-c', script], text=True, capture_output=True,
                                env=dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'],
                                         BOOT_TEST_LOG=str(root / 'rebuilds')))
        return result, cmdline.read_text()

    def test_luks_conversion_preserves_root_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = f'cryptdevice=UUID={UUID}:cryptlvm root=/dev/ArchinstallVg/root rootflags=subvol=@ rw zswap.enabled=0 loglevel=7\n'
            result, updated = self.run_hook(root, original)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f'rd.luks.name={UUID}=cryptlvm', updated)
            self.assertNotIn('cryptdevice=', updated)
            self.assertIn('root=/dev/ArchinstallVg/root rootflags=subvol=@ rw zswap.enabled=0', updated)
            self.assertIn('quiet loglevel=3', updated)
            self.assertNotIn('loglevel=7', updated)
            result, repeated = self.run_hook(root, updated)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(updated, repeated)
            self.assertEqual((root / 'rebuilds').read_text(), '-P\n-P\n')

    def test_rejects_invalid_boot_configuration_before_replacing_cmdline(self):
        cases = [
            ('cryptdevice=/dev/vda2:root root=/dev/mapper/root\n', 'default_uki="image"\n'),
            ('rw\n', 'default_uki="image"\n'),
            ('root=/dev/vda2 rw\n', 'default_image="image"\n'),
            ('root=/dev/vda2 rw\n', 'ALL_config="/etc/mkinitcpio.conf"\ndefault_uki="image"\n'),
        ]
        for parameters, preset in cases:
            with self.subTest(parameters=parameters, preset=preset), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result, after = self.run_hook(root, parameters, preset)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(after, parameters)
                self.assertFalse((root / 'rebuilds').exists())


class SessionTests(unittest.TestCase):
    def test_autologin_targets_selected_user_without_restarting_getty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'autologin.conf'
            login_defs = root / 'login.defs'
            login_defs.write_text('# Keep this comment\nHUSHLOGIN_FILE .hushlogin\nUID_MIN 1000\nHUSHLOGIN_FILE old\n')
            binary = root / 'bin'
            binary.mkdir()
            command = binary / 'systemctl'
            command.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SESSION_TEST_LOG"\n')
            command.chmod(0o755)
            script = (REPO / 'modules/desktop/hyprland/scripts/50_session.sh').read_text()
            script = script.replace('/etc/systemd/system/getty@tty1.service.d/autologin.conf', str(config))
            script = script.replace('/etc/login.defs', str(login_defs))
            subprocess.run(['bash', '-c', script], check=True,
                           env=dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'],
                                    DOTFILES_REPO=str(REPO), USERNAME='tester', SESSION_TEST_LOG=str(root / 'calls')))
            self.assertIn('ExecStart=\nExecStart=-/usr/bin/agetty --autologin tester', config.read_text())
            self.assertIn('--noissue --skip-login - ${TERM}', config.read_text())
            self.assertEqual((root / 'calls').read_text(),
                             'set-default graphical.target\n'
                             '--global enable hyprpolkitagent.service\n'
                             '--global enable hypridle.service\n')
            self.assertEqual(login_defs.read_text(), '# Keep this comment\nUID_MIN 1000\nHUSHLOGIN_FILE /etc/hushlogins\n')

    def run_profile(self, overrides=None, interactive=True, login=True, start_status=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'bin'
            binary.mkdir()
            command = binary / 'uwsm'
            command.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SESSION_TEST_LOG"\n'
                               'if [ "$1" = start ]; then exit "$SESSION_TEST_STATUS"; fi\n')
            command.chmod(0o755)
            (binary / 'desktop-session').symlink_to(
                REPO / 'modules/desktop/hyprland/files/usr/local/bin/desktop-session')
            additions = root / 'shell.d'
            additions.mkdir()
            (additions / 'hyprland.sh').write_text(
                (REPO / 'modules/desktop/hyprland/files/etc/bash.bashrc.d/hyprland.sh').read_text())
            profile = root / 'bash.bashrc'
            source = (REPO / 'modules/base/bash/files/etc/bash.bashrc').read_text()
            source = source.replace('/etc/bash.bashrc.d', str(additions))
            source = source.replace('/etc/profile.d', str(root / 'empty-profile.d'))
            profile.write_text(source)
            env = dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'], HOME=str(root),
                       XDG_VTNR='1', SSH_CONNECTION='', WAYLAND_DISPLAY='', DISPLAY='',
                       IN_UWSM_ENV_PRELOADER='false', SESSION_TEST_LOG=str(root / 'calls'),
                       SESSION_TEST_STATUS=str(start_status),
                       SESSION_TEST_PROFILE=str(profile))
            env.update(overrides or {})
            # Run the real profile in a shell that survives the session command.
            result = subprocess.run(['bash', '--noprofile', '--norc', ('-lic' if login else '-ic') if interactive else '-c',
                                     'source "$SESSION_TEST_PROFILE"; source "$SESSION_TEST_PROFILE"; printf "terminal\\n"'],
                                    env=env, text=True, capture_output=True)
            calls = (root / 'calls').read_text() if (root / 'calls').exists() else ''
            return result, calls

    def test_normal_exit_and_startup_failure_return_to_terminal(self):
        for status in (0, 1):
            with self.subTest(status=status):
                result, calls = self.run_profile(start_status=status)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('terminal', result.stdout)
                self.assertEqual(calls, 'check may-start\nstart -e -D Hyprland hyprland.desktop\n')

    def test_other_consoles_ssh_existing_sessions_and_preloader_do_not_start(self):
        cases = [
            {'XDG_VTNR': '2'}, {'XDG_VTNR': ''}, {'SSH_CONNECTION': 'remote'},
            {'WAYLAND_DISPLAY': 'wayland-1'}, {'DISPLAY': ':0'},
            {'IN_UWSM_ENV_PRELOADER': 'true'},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                result, calls = self.run_profile(overrides)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, '')
        result, calls = self.run_profile(login=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, '')
        result, calls = self.run_profile(interactive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, '')
