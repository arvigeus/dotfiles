import QtQuick
import QtQuick.Controls
import "."

TextField {
    id: root

    implicitHeight: Theme.controlHeight + 4
    color: Theme.text
    placeholderTextColor: Theme.muted
    selectionColor: Theme.accent
    selectedTextColor: Theme.accentText
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSize
    leftPadding: Theme.spacingMedium
    rightPadding: Theme.spacingMedium
    selectByMouse: true
    inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText

    background: Rectangle {
        color: Theme.surface
        radius: Theme.controlRadius
        border.width: 1
        border.color: root.activeFocus ? Theme.accent : Theme.border
    }
}
