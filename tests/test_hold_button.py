"""Hold confirmation must survive the key repeat a Wayland client synthesizes."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import support

UI = support.DESKTOP / 'ui'

# QML Test cannot mark key events as repeats, so a PySide6 view drives the
# unchanged button sources. Theme and the Quickshell tooltip are stand-ins.
THEME = """pragma Singleton
import QtQuick
QtObject {
    readonly property color text: "#eeeeee"
    readonly property color muted: "#999999"
    readonly property color accent: "#3388ff"
    readonly property color accentSurface: "#223355"
    readonly property color raised: "#333333"
    readonly property color danger: "#ff3333"
    readonly property string fontFamily: "sans-serif"
    readonly property int fontSize: 14
    readonly property int iconSize: 18
    readonly property int controlHeight: 34
    readonly property int controlRadius: 6
}
"""
TOOLTIP = """import QtQuick
Item {
    property Item target
    property string text
    property int maximumLineCount
}
"""
VIEW = """import QtQuick
import "ui"
Item {
    width: 320; height: 120
    property int confirmations: 0
    HoldButton {
        objectName: "hold"
        width: 200
        text: "Hold to delete"
        holdDuration: 300
        onConfirmed: parent.confirmations++
    }
}
"""
DRIVER = r"""
import sys
from PySide6.QtCore import QEvent, Qt, QUrl, qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest

warnings = []
qInstallMessageHandler(lambda kind, context, text: warnings.append(text) if kind != QtMsgType.QtDebugMsg else None)
app = QGuiApplication(sys.argv)
view = QQuickView()
view.setSource(QUrl.fromLocalFile(sys.argv[1]))
if view.status() != QQuickView.Status.Ready:
    sys.exit('view failed: ' + '; '.join(str(error) for error in view.errors()))
view.show()
root = view.rootObject()
hold = root.findChild(QQuickItem, 'hold')
hold.forceActiveFocus()
QTest.qWait(50)

def key(kind, repeat):
    QGuiApplication.sendEvent(view, QKeyEvent(kind, Qt.Key_Space, Qt.NoModifier, ' ', repeat))
    app.processEvents()

def check(condition, message):
    if not condition:
        sys.exit(f'{message}: confirmations={root.property("confirmations")} down={hold.property("down")} progress={hold.property("progress")}')

def held(milliseconds):
    # Wayland clients receive each repeat as a release/press pair.
    key(QEvent.KeyPress, False)
    for _ in range(milliseconds // 25):
        QTest.qWait(25)
        key(QEvent.KeyRelease, True)
        key(QEvent.KeyPress, True)
    check(hold.property('down'), 'a repeated key released the button')

held(150)
check(hold.property('progress') > 0.3, 'repeats restarted the hold')
key(QEvent.KeyRelease, False)
check(root.property('confirmations') == 0 and hold.property('progress') == 0, 'early release did not cancel')
held(500)
check(root.property('confirmations') == 1, 'held key did not confirm exactly once')
key(QEvent.KeyRelease, False)
check(not hold.property('down') and hold.property('progress') == 0, 'release did not reset the hold')
check(root.property('confirmations') == 1, 'release confirmed again')
check(not warnings, 'QML warnings: ' + '; '.join(warnings))
print('HOLD_PASS')
"""


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 is required')
class HoldButtonTests(unittest.TestCase):
    def test_repeated_key_is_one_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ui').mkdir()
            for name in (
                'HoldButton.qml',
                'ShellButton.qml',
                'ButtonBackground.qml',
                'Icon.qml',
                'ShellText.qml',
            ):
                shutil.copyfile(UI / name, root / 'ui' / name)
            shutil.copytree(support.DESKTOP / 'icons', root / 'icons')
            (root / 'ui/Theme.qml').write_text(THEME)
            (root / 'ui/PassiveToolTip.qml').write_text(TOOLTIP)
            (root / 'ui/qmldir').write_text('singleton Theme 1.0 Theme.qml\n')
            (root / 'view.qml').write_text(VIEW)
            (root / 'driver.py').write_text(DRIVER)
            result = subprocess.run(
                [sys.executable, '-I', str(root / 'driver.py'), str(root / 'view.qml')],
                env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                text=True,
                capture_output=True,
                timeout=30,
            )
        log = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, log)
        self.assertIn('HOLD_PASS', log)
