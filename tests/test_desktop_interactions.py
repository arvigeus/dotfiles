"""Run production interaction ownership and drawer input with isolated settings."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import support

DESKTOP = support.DESKTOP
QS = support.QS


@unittest.skipUnless(QS, 'Quickshell is required')
class DesktopInteractionTests(unittest.TestCase):
    def test_replacement_dismissal_keyboard_and_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            support.copy_theme_ui(root)
            for name in (
                'icons',
                'drawers',
                'launcher',
                'bar',
                'integrations',
                'spaces',
            ):
                shutil.copytree(DESKTOP / name, root / name)
            # Only native surface and shortcut registration need substitutes.
            # The owner, geometry, input, controls, persistence and launcher run
            # unchanged. Native layer focus/hotplug remain live acceptance checks.
            path = root / 'ui/InteractionWindow.qml'
            source = path.read_text().replace(
                'PanelWindow {',
                'FloatingWindow {\n    implicitWidth: 1280; implicitHeight: 720',
                1,
            )
            source = source.replace(
                '    anchors { top: true; bottom: true; left: true; right: true }\n', ''
            )
            source = source.replace('    exclusionMode: ExclusionMode.Ignore\n', '')
            source = re.sub(r'^    WlrLayershell\..*\n', '', source, flags=re.M)
            path.write_text(source)
            path = root / 'bar/Bar.qml'
            source = path.read_text().replace(
                'PanelWindow {', 'FloatingWindow {\n    implicitWidth: 1280', 1
            )
            source = source.replace(
                '    anchors { top: true; left: true; right: true }\n', ''
            )
            source = source.replace('    exclusiveZone: Theme.pillHeight\n', '')
            source = re.sub(r'^    WlrLayershell\..*\n', '', source, flags=re.M)
            path.write_text(source)
            for name in ('ui/DrawerHost.qml', 'launcher/Launcher.qml'):
                path = root / name
                source = re.sub(
                    r'^    WlrLayershell\..*\n', '', path.read_text(), flags=re.M
                )
                shortcut = (
                    'Instantiator' if name == 'ui/DrawerHost.qml' else 'GlobalShortcut'
                )
                source = re.sub(
                    r'    ' + shortcut + r' \{.*?\n    \}\n',
                    '',
                    source,
                    count=1,
                    flags=re.S,
                )
                path.write_text(source)
            # Display popup Escape must cancel its edit instead of dismissing the host.
            (root / 'drawers/displays/backend.py').write_text("""import json,sys
state={"available":True,"token":"fixture","displays":[{"name":"test-output","identity":["test-output"],"label":"Test monitor","enabled":True,"mode":"1920x1080@60.00Hz","modes":["1920x1080@60.00Hz"],"scale":1,"transform":0,"x":0,"y":0,"mirror":"none","dpms":True}]}
if __name__=="__main__":
 for line in sys.stdin:
  json.loads(line)
  print(json.dumps(dict(ok=True,error="",data=state)),flush=True)
""")
            (root / 'drawers/displays/brightness.py').write_text(
                'import json,sys;json.loads(sys.stdin.readline());print(json.dumps(dict(ok=True,values=[])))'
            )
            (root / 'drawers/bluetooth/backend.py').write_text("""import json,sys
for line in sys.stdin:
 request=json.loads(line)
 if request.get('active'):print(json.dumps(dict(type='state',available=True,adapters=[dict(key='a',name='Laptop',address='00',powered=True)],devices=[])),flush=True)
 else:print(json.dumps(dict(type='scan',key='')),flush=True)
""")
            # Storage uses fixture inventory; opening or dismissing must never touch host disks.
            (root / 'drawers/disks/backend.py').write_text("""import json,sys
volume=dict(key="vault",identity="vault",label="Vault",device="/dev/test1",fs="crypto_LUKS",size=1000,capacity=None,free=None,used=None,capacityError="",mounts=[],encrypted=True,locked=True,canMount=False,canUnmount=False,reason="",target="/")
drive=dict(key="test-drive",identity="drive",label="Test drive",size=1000,connection="usb",removable=True,canEject=True,ejectReason="",healthSupported=True,volumes=[volume])
for line in sys.stdin:
 json.loads(line)
 print(json.dumps(dict(ok=True,error="",data=dict(drives=[drive],editorAvailable=False))),flush=True)
""")
            from test_system_drawer import snapshot as system_snapshot

            (root / 'drawers/system/backend.py').write_text(
                'import json\nprint(json.dumps(' + repr(system_snapshot()) + '))\n'
            )
            # Power drawers use fixture inventory and never mutate host profiles.
            from test_power_drawers import snapshot as power_snapshot

            (root / 'drawers/power/backend.py').write_text(
                'import json,sys\n'
                f'state={power_snapshot()!r}\n'
                'for line in sys.stdin:\n'
                ' request=json.loads(line)\n'
                ' if request["op"]=="profile":state["profiles"]["active"]=request["value"]\n'
                ' print(json.dumps(dict(ok=True,error="",data=state)),flush=True)\n'
            )
            # Observe real page creation/destruction, including unrelated pages.
            (root / 'ui/ProbeState.qml').write_text("""pragma Singleton
import QtQuick
QtObject {
    property var events: []
    function record(event) { events = events.concat([event]); }
    function count(event) { return events.filter(value => value === event).length; }
}
""")
            with (root / 'ui/qmldir').open('a') as manifest:
                manifest.write('singleton ProbeState 1.0 ProbeState.qml\n')
            for key, name in (
                ('displays', 'Displays'),
                ('spaces', 'Spaces'),
                ('wifi', 'Wifi'),
                ('bluetooth', 'Bluetooth'),
            ):
                path = root / f'drawers/{name}Drawer.qml'
                source = path.read_text()
                if not re.search(r'^import QtQuick$', source, flags=re.M):
                    source = 'import QtQuick\n' + source
                source = source.replace(
                    'DrawerPage {',
                    f"""DrawerPage {{
    Item {{
        id: pageLifecycleProbe
        Component.onCompleted: ProbeState.record("created:{key}")
        Component.onDestruction: ProbeState.record("destroyed:{key}")
        Connections {{
            target: pageLifecycleProbe.parent
            function onActiveChanged() {{ ProbeState.record("active:{key}:" + pageLifecycleProbe.parent.active); }}
        }}
    }}
""",
                    1,
                )
                path.write_text(source)
            # An additional drawer requires no host/shell/window-rule changes. Its
            # timer stands in for discovery that must stop during the exit.
            (root / 'drawers/ProbeDrawer.qml').write_text("""import QtQuick
import QtQuick.Controls
import "../ui"
DrawerPage {
    id: root
    property int ticks: 0
    onActiveChanged: if (active && !screen) throw new Error("active before output assignment")
    initialFocus: field
    // Spread cold creation across incubation frames, then simulate device setup.
    Repeater { model: 200; delegate: Item {} }
    Component.onCompleted: {
        const until = Date.now() + 80;
        while (Date.now() < until) {}
        ProbeState.record("created:probe");
    }
    Component.onDestruction: ProbeState.record("destroyed:probe")
    Timer { interval: 1; repeat: true; running: root.active; onTriggered: root.ticks++ }
    TextField { id: field; objectName: "probeField" }
}
""")
            config = root / 'config/quickshell/desktop'
            config.mkdir(parents=True)
            (config / 'theme-mode').write_text('dark\n')
            (root / 'shell.qml').write_text("""import QtQuick
import QtTest
import Quickshell
import "ui"
import "drawers"
import "launcher"
import "bar"
import "drawers/notifications"
ShellRoot {
    id: root
    InteractionState { id: state }
    Launcher { id: launcher; interactionState: state }
    Drawers { id: drawers; interactionState: state }
    property var entranceProgress: []
    Connections {
        target: drawers
        function onCurrentPageChanged() {
            if (drawers.currentPage) root.entranceProgress.push(drawers.slideProgress);
        }
    }
    DrawerDefinition { id: probe; key: "probe"; title: "Probe"; source: Qt.resolvedUrl("drawers/ProbeDrawer.qml"); edge: DrawerDefinition.Left }
    DrawerDefinition { id: broken; key: "broken"; title: "Broken"; source: Qt.resolvedUrl("drawers/Missing.qml") }
    Bar {
        id: bar; screen: Quickshell.screens[0]; visible: true
        onDrawerRequested: key => drawers.toggleDrawer(key, screen)
    }
    Component {
        id: narrowComponent
        Bar {
            implicitWidth: 640
            screen: Quickshell.screens[0]
            visible: true
            onDrawerRequested: key => drawers.toggleDrawer(key, screen)
        }
    }
    property var narrowBar: null
    TestCase { id: input; when: false }
    property int stage: 0
    property real progressBefore: 0
    property int ticksBefore: 0
    property real buttonWidthBefore: 0
    property var badgeGeometry: []
    readonly property var badgeKeys: ["keyboard", "battery", "weather", "notifications", "tray"]
    function badgePositions() {
        return badgeKeys.map(key => {
            const button = find(bar.contentItem, key + "Button");
            const badge = find(button, key + "Badge");
            const icon = find(button, key + "Icon");
            const position = badge.mapToItem(button, 0, 0);
            const iconPosition = icon.mapToItem(button, 0, 0);
            const referenceIcon = find(bar.contentItem, "soundIcon");
            check(Math.abs(icon.mapToItem(bar.contentItem, 0, icon.height / 2).y
                - referenceIcon.mapToItem(bar.contentItem, 0, referenceIcon.height / 2).y) < 1,
                "badged icon is not aligned with the other icons: " + key);
            check(position.y > iconPosition.y && position.y < iconPosition.y + icon.height,
                "badge does not overlap the bottom of its icon: " + key);
            check(Math.abs(position.x + badge.width / 2 - iconPosition.x - icon.width) < 1,
                "badge is not centered on the icon's right edge: " + key);
            check(Math.abs(position.y + badge.height / 2 - iconPosition.y - icon.height) < 1,
                "badge is not centered on the icon's bottom edge: " + key);
            check(position.x >= 0 && position.x + badge.width <= button.width
                && position.y + badge.height <= button.height, "badge exceeds its button: " + key);
            if (button.entry.label === "" && button.entry.secondaryIconName === "")
                check(Math.abs(position.x + badge.width - button.width) < 1,
                    "trailing badge has extra right padding: " + key);
            return [button.mapToItem(bar.contentItem, 0, 0).x, button.width, badge.width];
        });
    }
    function checkBadgePositions() {
        check(JSON.stringify(badgePositions()) === JSON.stringify(badgeGeometry),
            "badge updates shifted the bar: " + JSON.stringify(badgePositions()) + " vs " + JSON.stringify(badgeGeometry));
    }
    property int previewWaits: 0
    property var previewKeys: ["tray", "clipboard", "capture",
        "wifi", "bluetooth", "sound", "microphone", "keyboard", "displays", "disks", "battery", "performance", "system", "weather", "events", "notifications"]
    function snapshot(name, window) {
        window = window || bar;
        const directory = Quickshell.env("DRAWER_PREVIEW_DIR");
        if (directory) find(window.contentItem, "statusViewport").parent.grabToImage(result => result.saveToFile(directory + "/" + name + ".png"));
    }
    function check(condition, message) { if (!condition) throw new Error(message); }
    function find(obj, name) {
        if (obj.objectName === name) return obj;
        for (const child of obj.children || []) { const found = find(child, name); if (found) return found; }
        return null;
    }
    function sole(key) {
        const owner = key === "launcher" ? launcher : key ? drawers : null;
        check(state.activeSurface === owner, "wrong active owner: " + key);
        check([launcher, drawers].filter(w => w.opened && w.visible).length === (owner ? 1 : 0), "surface overlap");
        if (owner === drawers) check(drawers.currentDrawer.key === key, "wrong category");
    }
    function open(key) { drawers.openDrawer(key, Quickshell.screens[0]); sole(key); }
    property int entranceWaits: 0
    Timer { id: steps; interval: 250; running: true; repeat: true; onTriggered: {
        try {
            // Loading now precedes entrance. Geometry/focus assertions wait for
            // both; the explicit motion/reversal stages still inspect mid-slide.
            if (drawers.opened && ((! [13,14,15].includes(stage) && drawers.slideProgress < 1)
                || (stage === 15 && drawers.slideProgress === 0))) {
                check(++entranceWaits < 40, "drawer did not finish loading/entering");
                return;
            }
            entranceWaits = 0;
            const screen = Quickshell.screens[0];
            if (stage === 0) {
                sole(null);
                check(drawers.currentPage === null && ProbeState.events.length === 0, "eager page loading");
                drawers.openDrawer("wifi", null); sole(null);
                launcher.openOn(screen); sole("launcher");
            } else if (stage === 1) {
                check(find(launcher.contentItem, "applicationSearch").activeFocus, "search activation focus");
                open("displays");
                launcher.dismiss(); sole("displays");
                drawers.openDrawer("wifi", null); sole("displays");
                drawers.toggleDrawer("wifi", null); sole("displays");
                drawers.openDrawer("unknown", screen); sole("displays");
            } else if (stage === 2) {
                check(ProbeState.count("created:displays") === 1 && !ProbeState.count("created:wifi")
                    && !ProbeState.count("created:bluetooth") && !ProbeState.count("created:spaces"), "unrelated content loaded");
                check(find(drawers.contentItem, "drawerClose").activeFocus, "lazy content activation focus");
                check(!find(bar.contentItem, "generalButton"), "removed General button remains");
                check(find(drawers.contentItem, "darkModeEnabled").checked, "saved dark mode not reflected");
                const card = find(drawers.contentItem, "drawerCard");
                check(card.x + card.width === drawers.width && card.y === 0
                    && card.height === drawers.height && card.radius === 0, "flush right geometry");
                input.mouseClick(card, card.width / 2, card.height - 20); sole("displays");
                input.mouseClick(find(drawers.contentItem, "darkModeEnabled"), 19, 17);
            } else if (stage === 3) {
                check(Theme.mode === "light", "theme save failed");
                input.keyClick(Qt.Key_Escape); sole(null);
                check(!drawers.currentPage.active, "closing page retained active services");
            } else if (stage === 4) {
                check(drawers.currentPage === null && ProbeState.count("destroyed:displays") === 1, "closed page retained: " + drawers.currentPage + " / " + drawers.slideProgress + " / " + drawers.keepVisible + " / " + JSON.stringify(ProbeState.events));
                open("displays");
            } else if (stage === 5) {
                const darkMode = find(drawers.contentItem, "darkModeEnabled");
                check(!darkMode.checked, "recreated page lost saved light mode");
                for (let count = 0; count < 12 && !darkMode.activeFocus; count++) input.keyClick(Qt.Key_Tab);
                check(darkMode.activeFocus, "Tab did not reach Dark mode");
                input.keyClick(Qt.Key_Space);
            } else if (stage === 6) {
                check(Theme.mode === "dark", "keyboard theme save");
                input.keyClick(Qt.Key_Space);
            } else if (stage === 7) {
                check(Theme.mode === "light", "keyboard theme return");
                input.mouseClick(drawers.contentItem, 10, 350); sole(null);
                open("displays");
                input.mouseClick(find(drawers.contentItem, "drawerClose"), 17, 17); sole(null);
                open("displays");
                input.mouseClick(find(bar.contentItem, "spacesButton"), 40, 17); sole("spaces");
            } else if (stage === 8) {
                const card = find(drawers.contentItem, "drawerCard");
                check(card.x === 0 && card.width === Theme.drawerWidth && card.height === drawers.height, "flush left geometry");
                check(find(drawers.contentItem, "drawerClose").activeFocus, "empty page focus fallback");
                const wifi = find(bar.contentItem, "wifiButton");
                const bluetooth = find(bar.contentItem, "bluetoothButton");
                check(wifi.parent === bluetooth.parent && wifi.parent.parent.objectName === "systemIsland", "system island");
                check(find(bar.contentItem,"systemButton").x>find(bar.contentItem,"performanceButton").x,"System is not last in system island");
                input.mouseClick(wifi, 17, 17); sole("wifi");
            } else if (stage === 9) {
                check(drawers.currentPage && drawers.currentPage.active && ProbeState.count("created:wifi") === 1, "Wi-Fi lazy load");
                const edit = find(drawers.contentItem, "networkEdit");
                const close = find(drawers.contentItem, "drawerClose");
                check(edit && edit.mapToItem(close.parent, edit.width, 0).x < close.x,
                    "network management icon is not before close in header");
                check(!find(drawers.currentPage, "networkEdit") && !find(drawers.contentItem, "vpnEdit"), "duplicate section management controls");
                input.mouseClick(find(drawers.contentItem, "wifiInfo"), 17, 17);
                check(drawers.currentPage.informationPopup?.visible, "Wi-Fi information did not open");
                input.keyClick(Qt.Key_Escape); sole("wifi");
                check(!drawers.currentPage.informationPopup, "Escape left Wi-Fi information open");
                check(!ProbeState.count("created:bluetooth"), "Bluetooth loaded with Wi-Fi");
                check(ProbeState.count("destroyed:spaces") === 1, "replacement retained old page");
                input.mouseClick(find(bar.contentItem, "bluetoothButton"), 17, 17); sole("bluetooth");
            } else if (stage === 10) {
                check(!find(drawers.contentItem, "networkEdit"), "Wi-Fi header action leaked into another drawer");
                check(ProbeState.count("created:bluetooth") === 1 && ProbeState.count("destroyed:wifi") === 1, "category replacement lifecycle");
                input.mouseClick(find(bar.contentItem, "bluetoothButton"), 17, 17); sole(null);
            } else if (stage === 11) {
                check(drawers.currentPage === null && !drawers.visible && state.screen === null, "closed host retained page/output");
                // Registration is open-ended, with no fixed count or category switches.
                drawers.definitions = Array.from(drawers.definitions).concat([probe, broken]);
                open("probe");
                drawers.openDrawer("unknown", screen); sole("probe");
            } else if (stage === 12) {
                check(drawers.currentPage && drawers.currentPage.ticks > 0, "additional drawer active backend");
                check(find(drawers.contentItem, "probeField").activeFocus, "additional drawer focus");
                ticksBefore = drawers.currentPage.ticks;
                steps.interval = 40;
                drawers.dismiss(); sole(null);
                check(drawers.visible && drawers.mask !== null && !drawers.currentPage.active
                    && !find(drawers.contentItem, "drawerCard").enabled, "closing input/services");
            } else if (stage === 13) {
                check(drawers.slideProgress > 0 && drawers.slideProgress < 1, "exit motion");
                check(drawers.currentPage.ticks === ticksBefore, "backend continued during exit");
                progressBefore = drawers.slideProgress;
                open("probe");
                check(drawers.slideProgress === progressBefore && ProbeState.count("created:probe") === 1, "rapid reopen recreated/snapped page");
            } else if (stage === 14) {
                check(drawers.slideProgress > progressBefore, "reopen did not reverse motion");
                open("wifi");
                check(drawers.slideProgress === 0, "replacement retained outgoing motion");
            } else if (stage === 15) {
                const card = find(drawers.contentItem, "drawerCard");
                check(drawers.slideProgress > 0 && drawers.slideProgress < 1
                    && card.x > drawers.width - card.width && card.x < drawers.width, "right entrance");
                launcher.openOn(screen); sole("launcher");
                check(!drawers.visible && drawers.currentPage === null, "launcher replacement retained page");
                steps.interval = 250;
            } else if (stage === 16) {
                open("broken");
            } else if (stage === 17) {
                check(find(drawers.contentItem, "drawerPageLoader").status === Loader.Error, "missing source error state");
                check(find(drawers.contentItem, "drawerClose").activeFocus, "failed page lost close focus");
                input.keyClick(Qt.Key_Escape); sole(null);
            } else if (stage === 18) {
                open("probe");
            } else if (stage === 19) {
                drawers.dismiss(); drawers.resetPresentation(); sole(null);
                check(drawers.currentPage === null && !drawers.visible, "reset drawer retained");
                check(ProbeState.count("destroyed:probe") === 2, "additional page lifetime");
            } else if (stage >= 20 && stage < 20 + previewKeys.length) {
                if (stage > 20) {
                    if (drawers.currentPage === null && ++previewWaits < 20) return;
                    previewWaits = 0;
                    check(drawers.currentPage !== null, "preview page did not load");
                    if (["wifi", "bluetooth"].includes(previewKeys[stage - 21])) {
                        const title = find(drawers.contentItem, "drawerTitleBlock");
                        const actions = find(drawers.contentItem, "drawerHeaderActions");
                        check(!find(drawers.contentItem, "drawerSubtitle"), "adapter subtitle remains in header");
                        const infoName = previewKeys[stage - 21] === "wifi" ? "wifiInfo" : "bluetoothInfo";
                        check(find(drawers.contentItem, infoName)?.iconName === "info", "header information action missing");
                        check(Math.abs(title.mapToItem(drawers.contentItem, 0, title.height / 2).y
                            - actions.mapToItem(drawers.contentItem, 0, actions.height / 2).y) < 1, "title block is not vertically centered");
                    }
                    if (previewKeys[stage - 21] === "tray")
                        check(find(drawers.contentItem, "trayScroll"), "tray controls missing");
                    else if (previewKeys[stage - 21] === "wifi")
                        check(find(drawers.contentItem, "networkScroll") && find(drawers.contentItem, "wifiToggle")
                            && find(drawers.contentItem, "wifiInfo") && !find(drawers.currentPage, "wifiInfo"), "Wi-Fi controls missing");
                    else if (previewKeys[stage - 21] === "bluetooth")
                        check(find(drawers.contentItem, "bluetoothPower") && find(drawers.contentItem, "bluetoothScan")
                            && find(drawers.contentItem, "bluetoothEdit") && !find(drawers.currentPage, "bluetoothScan"), "Bluetooth controls missing");
                    else if (previewKeys[stage - 21] === "clipboard")
                        check(find(drawers.contentItem, "clipboardPause"), "clipboard controls missing");
                    else if (previewKeys[stage - 21] === "system") {
                        const page = drawers.currentPage, info = find(drawers.contentItem,"systemInfo");
                        check(find(page,"systemBoot") && find(page,"systemServices") && find(page,"systemRepairSigning") && find(page,"systemCheckPackages") && info && find(bar.contentItem,"systemButton"),"system controls missing");
                        check(!find(drawers.contentItem,"systemRefresh") && !find(drawers.contentItem,"systemLogs") && !find(page,"systemCleanup"),"duplicate system actions remain");
                        info.clicked();
                        check(page.informationPopup?.visible && page.service.section === "info" && drawers.escapeHandler,"system information did not open");
                        input.keyClick(Qt.Key_Escape); sole("system");
                        check(!page.informationPopup && !drawers.escapeHandler,"Escape did not close only system information");
                        check(!find(page,"systemMaintenance") && page.service.section === "","maintenance nesting remains");
                        for(const name of ["systemRepairSigning","systemCheckPackages"])
                            check(Math.abs(find(page,name).width-page.width)<2,"direct action squeezed: "+name);
                    }
                    else if (previewKeys[stage - 21] === "capture")
                        check(find(drawers.contentItem, "captureScreenshot") && find(drawers.contentItem, "captureScreenshotOptions"), "capture controls missing");
                    else if (previewKeys[stage - 21] === "sound")
                        check(find(drawers.contentItem, "audioOutputsEmpty") && find(drawers.contentItem, "audioScroll"), "playback controls missing");
                    else if (previewKeys[stage - 21] === "microphone")
                        check(find(drawers.contentItem, "microphoneInputsEmpty") && find(drawers.contentItem, "microphoneScroll"), "microphone controls missing");
                    else if (previewKeys[stage - 21] === "keyboard") {
                        check(find(drawers.contentItem, "keyboardTestInput") && find(drawers.contentItem, "language-en"), "keyboard controls missing");
                        find(drawers.contentItem, "keyboardHelp").clicked();
                        check(drawers.currentPage.referencePopup.visible && drawers.escapeHandler, "keyboard help Escape handler missing");
                        input.keyClick(Qt.Key_Escape);
                        sole("keyboard");
                        check(!drawers.currentPage.referencePopup.visible && !drawers.escapeHandler, "Escape did not close only keyboard help");
                    }
                    else if (previewKeys[stage - 21] === "displays") {
                        check(find(drawers.contentItem, "displayScroll"), "display controls missing");
                        const options = find(drawers.contentItem, "displayOptions:test-output");
                        check(options, "display card missing");
                        input.mouseClick(options, options.width / 2, options.height / 2);
                        check(options.menu.visible && drawers.escapeHandler, "popup Escape handler not forwarded");
                        input.keyClick(Qt.Key_Escape);
                        sole("displays");
                        check(!options.menu.visible && !drawers.escapeHandler, "Escape did not close only the display popup");
                    }
                    else if (previewKeys[stage - 21] === "weather") {
                        check(find(drawers.contentItem, "weatherLocation"), "clock/weather controls missing");
                        const page = drawers.currentPage, focus = find(page, "focusToggle"), add = find(page, "reminderAdd");
                        check(Math.abs(focus.width - page.width) < 2 && Math.abs(add.width - page.width) < 2, "reminder section buttons are squeezed in host");
                        for (const [button, name] of [[focus, "focusPopup"], [add, "reminderPopup"]]) {
                            button.clicked();
                            const popup = button.data.find(item => item.objectName === name);
                            check(popup.visible && Math.abs(popup.width - page.width) < 2 && popup.width > 260, "reminder popup is squeezed in host");
                            input.keyClick(Qt.Key_Escape); sole("weather");
                            check(!popup.visible && !drawers.escapeHandler, "Escape did not close only reminder popup");
                        }
                    }
                    else if (previewKeys[stage - 21] === "disks") {
                        check(find(drawers.contentItem, "disksScroll"), "storage controls missing");
                        const health = find(drawers.contentItem, "diskHealth:test-drive"); health.clicked();
                        check(health.menu.visible && drawers.escapeHandler, "health popover Escape handler missing");
                        input.keyClick(Qt.Key_Escape); sole("disks");
                        check(!health.menu.visible && !drawers.escapeHandler, "Escape did not close only health popover");
                        find(drawers.contentItem, "volumeAction:vault").clicked();
                        check(drawers.currentPage.unlockPopup.visible && drawers.escapeHandler, "unlock Escape handler missing");
                        input.keyClick(Qt.Key_Escape); sole("disks");
                        check(!drawers.currentPage.unlockPopup.visible && !drawers.escapeHandler, "Escape did not close only unlock popup");
                        const cleanup = find(drawers.currentPage, "systemCleanup"); cleanup.clicked();
                        check(cleanup.popupOpen && drawers.escapeHandler, "cleanup popover Escape handler missing");
                        check(Math.abs(cleanup.width - drawers.currentPage.width) < 2, "cleanup footer is squeezed");
                        input.keyClick(Qt.Key_Escape); sole("disks");
                        check(!cleanup.popupOpen && !drawers.escapeHandler, "Escape did not close only cleanup popup");
                    }
                    else if (previewKeys[stage - 21] === "battery") {
                        check(!!find(drawers.contentItem, "batteryPercentage"), "battery controls missing");
                        check(find(drawers.contentItem, "batteryRefresh"), "battery header missing");
                        check(!find(drawers.currentPage, "batteryPerformance"), "battery retained cross-drawer link");
                    }
                    else if (previewKeys[stage - 21] === "performance") {
                        check(find(drawers.contentItem, "cpuUsage").value === "23%", "performance controls missing");
                        check(find(drawers.contentItem, "performanceMonitor"), "performance header missing");
                        check(!find(drawers.currentPage, "performanceBattery"), "performance retained cross-drawer link");
                        check(!find(drawers.contentItem, "performanceHardware:asus"), "competing hardware profile editor remains");
                        check(!find(drawers.contentItem, "cpuBoost"), "independent boost control remains");
                    }
                    else if (previewKeys[stage - 21] === "events")
                        check(find(drawers.contentItem, "eventsDrawer") && find(drawers.contentItem, "taskSearch"), "calendar/tasks controls missing");
                }
                const key = previewKeys[stage - 20];
                const button = find(bar.contentItem, key + "Button");
                check(button && button.visible && button.enabled, "missing preview button: " + key);
                input.mouseClick(button, button.width / 2, 17); sole(key);
            } else if (stage === 20 + previewKeys.length + 0) {
                check(drawers.currentPage !== null, "last preview page did not load");
                check(find(drawers.contentItem, "notificationsDrawer"), "notification controls missing");
                check(["trayIsland", "toolsIsland", "systemIsland", "notificationsIsland"]
                    .every(name => find(bar.contentItem, name)), "missing islands");
                NotificationCenter.state = NotificationCenter.normalized({items:[{id:"badge-a",seen:false},{id:"badge-b",seen:false}],paused:false});
                snapshot("bar-light");
                const wifi = find(bar.contentItem, "wifiButton");
                buttonWidthBefore = wifi.width;
                wifi.entry.label = "99%";
                wifi.entry.iconName = "bluetooth";
                wifi.entry.badge = "5";
                wifi.entry.attention = true;
                wifi.entry.available = false;
            } else if (stage === 20 + previewKeys.length + 1) {
                const wifi = find(bar.contentItem, "wifiButton");
                const bell = find(bar.contentItem, "notificationsButton");
                check(bell.entry.badge === "2" && bell.entry.attention && bell.entry.description.includes("2 unseen"), "bell missed unseen count");
                NotificationCenter.state = NotificationCenter.normalized({items:Array.from({length:100}, (_, index) => ({id:"unseen-" + index,seen:false})),paused:false});
                check(bell.entry.badge === "99+" && bell.entry.description.includes("100 unseen"), "notification badge overflowed or lost its exact tooltip count");
                NotificationCenter.state = {items:[],paused:true};
                check(bell.entry.badge === "" && !bell.entry.attention && bell.entry.description.includes("Do Not Disturb"), "bell retained stale unread state");
                NotificationCenter.state = {items:[],paused:false};
                check(wifi.width > buttonWidthBefore, "status label did not resize button");
                check(find(wifi, "wifiIcon").name === "bluetooth"
                    && find(wifi, "wifiBadge").text === "5", "status did not update in place");
                input.mouseClick(wifi, wifi.width / 2, 17); sole("notifications");
                wifi.entry.label = ""; wifi.entry.iconName = "wifi"; wifi.entry.badge = "";
                wifi.entry.attention = false; wifi.entry.available = true;
                Theme.setMode("dark");
                open("performance");
            } else if (stage === 20 + previewKeys.length + 2) {
                snapshot("bar-dark");
                for (const key of badgeKeys) find(bar.contentItem, key + "Button").entry.badge = "";
                const directory = Quickshell.env("DRAWER_PREVIEW_DIR");
                if (directory) find(drawers.contentItem, "drawerCard").grabToImage(result => result.saveToFile(directory + "/drawer.png"));
                narrowBar = narrowComponent.createObject(root);
            } else if (stage === 20 + previewKeys.length + 3) {
                badgeGeometry = badgePositions();
                for (const [index, value] of ["BG", "100%", "−19°", "99+", "99+"].entries())
                    find(bar.contentItem, badgeKeys[index] + "Button").entry.badge = value;
                const viewport = find(narrowBar.contentItem, "statusViewport");
                check(viewport.interactive && viewport.contentWidth > viewport.width, "narrow islands lost overflow: " + viewport.width + " / " + viewport.contentWidth + " / " + narrowBar.width + " / " + narrowBar.implicitWidth);
                check(viewport.parent.x > find(narrowBar.contentItem, "spacesButton").width, "narrow islands overlap Spaces");
                const before = viewport.contentX;
                input.mouseWheel(viewport, viewport.width / 2, 17, 0, -120, Qt.NoButton, Qt.NoModifier, 0);
                check(viewport.contentX > before, "narrow islands cannot scroll");
                viewport.contentX = viewport.contentWidth - viewport.width;
                const notifications = find(narrowBar.contentItem, "notificationsButton");
                input.mouseClick(notifications, notifications.width / 2, 17); sole("notifications");
                snapshot("bar-narrow", narrowBar);
                Theme.setMode("light");
            } else if (stage === 20 + previewKeys.length + 4) {
                checkBadgePositions();
                snapshot("bar-badges-light");
                drawers.dismiss();
            } else if (stage === 20 + previewKeys.length + 5) {
                for (const [index, value] of ["VI", "9%", "8°", "1", "3"].entries())
                    find(bar.contentItem, badgeKeys[index] + "Button").entry.badge = value;
                Theme.setMode("dark");
            } else if (stage === 20 + previewKeys.length + 6) {
                checkBadgePositions();
                snapshot("bar-badges-dark");
            } else if (stage === 20 + previewKeys.length + 7) {
                for (const key of badgeKeys) find(bar.contentItem, key + "Button").entry.badge = "";
            } else if (stage === 20 + previewKeys.length + 8) {
                checkBadgePositions();
                Theme.setMode("light");
                check(drawers.currentPage === null && !drawers.visible, "preview teardown");
                narrowBar.destroy();
                check(root.entranceProgress.length > 0 && root.entranceProgress.every(value => value === 0),
                    "page creation interrupted an entrance: " + JSON.stringify(root.entranceProgress));
                console.log("INTERACTIONS_PASS"); Qt.quit(); return;
            }
            stage++;
        } catch (e) { console.error("INTERACTIONS_FAIL", stage, e.message); Qt.quit(); }
    } }
}
""")
            (root / 'runtime').mkdir(mode=0o700)
            env = {
                **os.environ,
                'XDG_RUNTIME_DIR': str(root / 'runtime'),
                'QT_QPA_PLATFORM': 'offscreen',
                'XDG_CONFIG_HOME': str(root / 'config'),
                'XDG_DATA_HOME': str(root / 'data'),
                'XDG_STATE_HOME': str(root / 'state'),
                'XDG_CACHE_HOME': str(root / 'cache'),
                'PIPEWIRE_REMOTE': 'dotfiles-tests-unavailable',
                'XDG_DATA_DIRS': str(root / 'empty'),
            }
            for key in ('WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
                env.pop(key, None)
            result = subprocess.run(
                [QS, '--no-color', '-p', str(root / 'shell.qml')],
                env=env,
                text=True,
                capture_output=True,
                timeout=20,
            )
            log = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, log)
            self.assertNotIn('INTERACTIONS_FAIL', log)
            self.assertNotIn('TypeError', log)
            self.assertNotIn('ReferenceError', log)
            self.assertNotIn('Cannot open: file:', log)
            self.assertNotIn('Binding loop', log)
            self.assertIn('INTERACTIONS_PASS', log)
            self.assertEqual((config / 'theme-mode').read_text(), 'light\n')
