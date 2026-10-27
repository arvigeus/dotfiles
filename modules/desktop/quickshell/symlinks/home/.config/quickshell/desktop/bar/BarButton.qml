import "../ui"
import QtQuick
import QtQuick.Controls

Button {
    id: button

    property bool selected: false
    property bool urgent: false

    implicitWidth: Theme.controlHeight
    implicitHeight: Theme.controlHeight
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSize

    contentItem: ShellText {
        text: button.text
        color: button.urgent ? Theme.warning : Theme.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: ButtonBackground {
        highlighted: button.selected || button.urgent
        pressed: button.down
        idleColor: button.hovered ? Theme.raised : "transparent"
        color: button.urgent && !button.down ? Qt.tint(Theme.surface, Qt.rgba(Theme.warning.r, Theme.warning.g, Theme.warning.b, 0.16)) : button.down ? Theme.raised : button.selected ? Theme.accentSurface : idleColor
        border.color: button.urgent ? Theme.warning : button.selected ? Theme.accent : "transparent"
    }
}
