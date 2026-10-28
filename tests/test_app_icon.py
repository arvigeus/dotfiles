"""Load application icons from absolute paths with URL syntax in their names."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


UI = (
    Path(__file__).resolve().parents[1]
    / 'modules/desktop/quickshell'
    / 'symlinks/home/.config/quickshell/desktop/ui'
)
QS = shutil.which('qs')
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16"/></svg>\n'


@unittest.skipUnless(QS, 'Quickshell is required')
class AppIconTests(unittest.TestCase):
    def test_absolute_paths_are_file_names_not_url_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Desktop entries and audio clients may name any local file.
            paths = [root / 'icons/plain.svg', root / 'icons#dir/a#b?c%41 ü.svg']
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(SVG)
            # A decoded "%41" would name this file instead.
            (root / 'icons#dir/a#b?cA ü.svg').write_text('not an image\n')
            icons = '\n'.join(
                f'    UI.AppIcon {{ icon: {json.dumps(str(path))} }}' for path in paths
            )
            qml = (
                """import QtQuick
import Quickshell
import "ui" as UI
FloatingWindow {
    id: root
    implicitWidth: 200; implicitHeight: 100
    Row { id: row
"""
                + icons
                + """
    }
    property int ticks: 0
    Timer { interval: 100; running: true; repeat: true; onTriggered: {
        const states = Array.from(row.children).map(icon => icon.children[0].status);
        if (states.includes(Image.Loading) && ticks++ < 50) return;
        console.log(states.every(status => status === Image.Ready) ? "APP_ICON_PASS" : "APP_ICON_FAIL " + states);
        Qt.quit();
    } }
}
"""
            )
            shutil.copytree(UI, root / 'ui')
            (root / 'shell.qml').write_text(qml)
            config = root / 'config/quickshell/desktop'
            config.mkdir(parents=True)
            (config / 'theme-mode').write_text('dark\n')
            (root / 'runtime').mkdir(mode=0o700)
            env = {
                **os.environ,
                'QT_QPA_PLATFORM': 'offscreen',
                'XDG_CONFIG_HOME': str(root / 'config'),
                'XDG_RUNTIME_DIR': str(root / 'runtime'),
            }
            for key in ('WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
                env.pop(key, None)
            result = subprocess.run(
                [QS, '--no-color', '-p', str(root / 'shell.qml')],
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
        log = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, log)
        self.assertIn('APP_ICON_PASS', log)
        self.assertNotIn('TypeError', log)
