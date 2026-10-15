import QtQuick
import QtQuick.Controls
import "../../ui"

Button {
    id: root
    implicitHeight: Theme.controlHeight
    padding: Theme.spacingMedium
    hoverEnabled: true
    opacity: enabled ? 1 : 0.45
    contentItem: ShellText {
        text: root.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: ButtonBackground {
        idleColor: Theme.raised
        highlighted: root.hovered || root.visualFocus || root.checked
        pressed: root.down
    }
}
