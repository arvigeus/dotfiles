"""Media dialogs inherit the desktop palette and accept a single input."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class MediaDialogTests(unittest.TestCase):
    def test_single_file_launchers(self):
        for kind in ('audio', 'video'):
            module = REPO / f'modules/media/tools/{kind}'
            desktop = module / f'files/usr/local/share/applications/{kind}-tools.desktop'
            self.assertIn(f'Exec=/usr/local/bin/{kind}-tools %f\n', desktop.read_text())
            subprocess.run(['desktop-file-validate', str(desktop)], check=True, capture_output=True)
            library = module / f'files/usr/local/lib/{kind}-tools'
            name = 'gui' if kind == 'audio' else 'video_gui'
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(library))
            script = f'''
from unittest.mock import patch
import {name} as gui
with patch.object(gui.QFileDialog, 'getOpenFileName', return_value=('', '')) as picker:
    with patch('sys.argv', ['{kind}-tools']):
        assert gui.main() == 0
    assert picker.call_count == 1
'''
            result = subprocess.run([sys.executable, '-c', script], env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('dbus-run-session'), 'An isolated session bus is required')
    def test_native_palette_at_startup_and_after_mode_changes(self):
        if not Path('/usr/lib/qt6/plugins/platformthemes/KDEPlasmaPlatformTheme6.so').exists():
            self.skipTest('The KDE Qt platform theme is required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ, MEDIA_TEST_REPO=str(REPO), HOME=str(root),
                       XDG_CONFIG_HOME=str(root / 'config'), XDG_DATA_HOME=str(root / 'data'),
                       XDG_STATE_HOME=str(root / 'state'), QT_QPA_PLATFORM='offscreen',
                       QT_QPA_PLATFORMTHEME='kde', UNION_STYLE_NAME='dotfiles')
            env.pop('QT_STYLE_OVERRIDE', None)
            script = '''
import importlib.util, os, sys, time
from pathlib import Path
from PySide6.QtDBus import QDBusConnection, QDBusMessage
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication
repo = Path(os.environ['MEDIA_TEST_REPO'])
spec = importlib.util.spec_from_file_location('desktop_theme', repo / 'modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop/ui/theme.py')
theme = importlib.util.module_from_spec(spec); spec.loader.exec_module(theme)
theme.SOURCE = repo / 'modules/look-and-feel/palette/symlinks/etc/desktop-palette.json'
theme.apply('dark', notifications=False)
sys.path[:0] = [str(repo / f'modules/media/tools/{kind}/files/usr/local/lib/{kind}-tools') for kind in ('audio', 'video')]
from gui import AudioTools
from video_gui import VideoTools
app = QApplication(['media-tools-theme-test'])
source = Path.home() / 'input.mkv'; source.touch()
windows = [cls(source, repo / f'modules/media/tools/{kind}/files/home/.config/{kind}-tools/presets.json')
           for kind, cls in [('audio', AudioTools), ('video', VideoTools)]]
for window in windows: window.show()
for mode in ('dark', 'light', 'dark'):
    theme.apply(mode, notifications=False)
    for kind in (0, 1, 2, 4):
        message = QDBusMessage.createSignal('/KGlobalSettings', 'org.kde.KGlobalSettings', 'notifyChange')
        message.setArguments([kind, 0])
        assert QDBusConnection.sessionBus().send(message)
    colors = theme.load()['palettes'][mode]
    deadline = time.monotonic() + 5
    while True:
        app.processEvents()
        if all(window.palette().color(QPalette.Window).name() == colors['background'] for window in windows): break
        assert time.monotonic() < deadline, (mode, app.palette().color(QPalette.Window).name())
        time.sleep(0.01)
    for window in windows:
        for widget in (window, window.tabs, window.output):
            assert widget.palette().color(QPalette.Window).name() == colors['background']
            assert widget.palette().color(QPalette.Text).name() == colors['text']
for window in windows: window.close()
'''
            result = subprocess.run(['dbus-run-session', '--', sys.executable, '-c', script],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == '__main__':
    unittest.main()
