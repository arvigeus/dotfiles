import QtQuick
import QtQuick.Controls
import "../ui"

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
        color: button.urgent ? Theme.danger : Theme.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: Theme.controlRadius
        color: button.down ? Theme.raised : button.selected ? Theme.accentSurface
            : button.hovered ? Theme.raised : "transparent"
        border.width: 1
        border.color: button.selected ? Theme.accent : "transparent"
    }
}
