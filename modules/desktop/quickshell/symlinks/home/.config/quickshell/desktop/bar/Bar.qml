import QtQuick
import Quickshell
import Quickshell.Wayland
import "../ui"

PanelWindow {
    id: bar

    anchors { top: true; left: true; right: true }
    implicitHeight: Theme.pillHeight
    exclusiveZone: Theme.pillHeight
    color: "transparent"

    // Keep the reservation mapped while fullscreen windows cover the Top layer.
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.namespace: "desktop-bar"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    mask: Region {}

    Surface {
        x: Theme.barInset
        y: Theme.pillTopPadding
        width: Math.min(label.implicitWidth + Theme.padding * 2,
            Math.max(0, bar.width - Theme.barInset * 2))
        height: Theme.controlHeight
        radius: Theme.pillRadius
        border.width: 0

        ShellText {
            id: label
            anchors.centerIn: parent
            width: Math.max(0, parent.width - Theme.padding * 2)
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: "Desktop"
        }
    }
}
