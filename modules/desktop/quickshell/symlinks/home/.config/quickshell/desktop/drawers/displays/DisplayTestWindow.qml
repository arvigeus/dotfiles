import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: overlay
    property var target: null
    property var controller: null
    readonly property bool identifying: controller?.mode === "identify"
    screen: target?.screen ?? null
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    visible: controller?.running ?? false
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "desktop-display-test"
    WlrLayershell.keyboardFocus: identifying ? WlrKeyboardFocus.None : WlrKeyboardFocus.Exclusive
    mask: identifying ? noInput : null
    Region { id: noInput }
    DisplayTestView {
        id: testView
        anchors.fill: parent
        mode: overlay.controller?.mode ?? "identify"
        record: overlay.target?.record ?? ({name: "", label: "", mode: ""})
        number: overlay.target?.number ?? 1
        onCloseRequested: overlay.controller.stop()
    }
    Shortcut { sequence: "Escape"; enabled: overlay.visible && !overlay.identifying; onActivated: overlay.controller.stop() }
    Shortcut { sequence: "Space"; enabled: overlay.visible && !overlay.identifying; onActivated: testView.advance(1) }
    Shortcut { sequence: "Right"; enabled: overlay.visible && !overlay.identifying; onActivated: testView.advance(1) }
    Shortcut { sequence: "Left"; enabled: overlay.visible && !overlay.identifying; onActivated: testView.advance(-1) }
    Shortcut { sequence: "H"; enabled: overlay.visible && !overlay.identifying; onActivated: testView.controlsVisible = !testView.controlsVisible }
}
