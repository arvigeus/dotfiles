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

    def test_console_settings_preserve_unlock_parameters_and_are_idempotent(self):
        for unlock in (f'cryptdevice=UUID={UUID}:cryptlvm', f'rd.luks.name={UUID}=cryptlvm'):
            with self.subTest(unlock=unlock), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                original = f'{unlock} root=/dev/ArchinstallVg/root rootflags=subvol=@ rw zswap.enabled=0 loglevel=7\n'
                result, updated = self.run_hook(root, original)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(unlock, updated)
                self.assertIn('root=/dev/ArchinstallVg/root rootflags=subvol=@ rw zswap.enabled=0', updated)
                self.assertIn('quiet loglevel=3', updated)
                self.assertNotIn('loglevel=7', updated)
                result, repeated = self.run_hook(root, updated)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(updated, repeated)
                self.assertEqual((root / 'rebuilds').read_text(), '-P\n-P\n')

    def test_disables_mitigations_and_replaces_existing_values(self):
        for existing in ('', 'mitigations=auto', 'mitigations=auto,nosmt mitigations=off'):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result, updated = self.run_hook(root, f'root=/dev/vda2 rw {existing}\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([p for p in updated.split() if p.split('=', 1)[0] == 'mitigations'],
                                 ['mitigations=off'])
                result, repeated = self.run_hook(root, updated)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(updated, repeated)

    def test_rejects_invalid_boot_configuration_before_replacing_cmdline(self):
        cases = [
            ('rw\n', 'default_uki="image"\n'),
            ('root=/dev/vda2 rw\n', 'default_image="image"\n'),
        ]
        for parameters, preset in cases:
            with self.subTest(parameters=parameters, preset=preset), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result, after = self.run_hook(root, parameters, preset)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(after, parameters)
                self.assertFalse((root / 'rebuilds').exists())

    def test_explicit_preset_configuration_remains_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            result, updated = self.run_hook(Path(directory), 'cryptdevice=/dev/vda2:root root=/dev/mapper/root rw\n',
                                            'ALL_config="/etc/mkinitcpio.conf"\ndefault_uki="image"\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('cryptdevice=/dev/vda2:root', updated)

    def test_firmware_graphics_replace_only_the_stock_arch_splash(self):
        preset = ('default_uki="image"\n'
                  'default_options="--splash /usr/share/systemd/bootctl/splash-arch.bmp"\n'
                  'fallback_options="--splash /custom/logo.bmp"\n'
                  'custom_options="--splash /usr/share/systemd/bootctl/splash-arch.bmp --other"\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, _ = self.run_hook(root, 'cryptdevice=/dev/vda2:root root=/dev/mapper/root rw\n', preset)
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = (root / 'presets/linux.preset').read_text()
            self.assertIn('default_options=""\n', updated)
            self.assertIn('fallback_options="--splash /custom/logo.bmp"\n', updated)
            self.assertIn('custom_options="--splash /usr/share/systemd/bootctl/splash-arch.bmp --other"\n', updated)


class SessionTests(unittest.TestCase):
    def test_autologin_targets_selected_user_without_restarting_getty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'autologin.conf'
            binary = root / 'bin'
            binary.mkdir()
            command = binary / 'systemctl'
            command.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SESSION_TEST_LOG"\n')
            command.chmod(0o755)
            script = (REPO / 'modules/desktop/hyprland/scripts/50_session.sh').read_text()
            script = script.replace('/etc/systemd/system/getty@tty1.service.d/autologin.conf', str(config))
            subprocess.run(['bash', '-c', script], check=True,
                           env=dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'],
                                    DOTFILES_REPO=str(REPO), USERNAME='tester', SESSION_TEST_LOG=str(root / 'calls')))
            self.assertIn('ExecStart=\nExecStart=-/usr/bin/agetty --autologin tester', config.read_text())
            self.assertIn('--noissue --skip-login - ${TERM}', config.read_text())
            self.assertEqual((root / 'calls').read_text(), 'set-default graphical.target\n')
        self.assertEqual((REPO / 'modules/desktop/hyprland/files/home/.hushlogin').read_text(), '')

    def run_profile(self, vt='1', may_start=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'bin'
            binary.mkdir()
            for name in ('uwsm', 'session-mode'):
                (binary / name).write_text('#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$SESSION_TEST_LOG"\n'
                                           'exit "$SESSION_TEST_STATUS"\n')
                (binary / name).chmod(0o755)
            env = dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'], XDG_VTNR=vt,
                       SESSION_TEST_LOG=str(root / 'calls'), SESSION_TEST_STATUS=str(may_start))
            profile = REPO / 'modules/desktop/hyprland/files/etc/profile.d/zz-session-mode.sh'
            result = subprocess.run(['sh', '-c', '. "$1"; echo terminal', 'sh', str(profile)],
                                    env=env, text=True, capture_output=True)
            calls = (root / 'calls').read_text() if (root / 'calls').exists() else ''
            return result, calls

    def test_tty1_login_execs_the_supervisor_and_never_reveals_a_prompt(self):
        result, calls = self.run_profile()
        self.assertNotIn('terminal', result.stdout)
        self.assertEqual(calls, 'uwsm check may-start\nsession-mode run\n')

    def test_other_consoles_and_refused_starts_keep_the_shell(self):
        result, calls = self.run_profile(vt='2')
        self.assertEqual((result.stdout, calls), ('terminal\n', ''))
        result, calls = self.run_profile(may_start=1)
        self.assertEqual((result.stdout, calls), ('terminal\n', 'uwsm check may-start\n'))
