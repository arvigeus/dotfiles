import QtQuick
import QtQuick.Controls

TextField {
    id: root
    implicitHeight: MovieStyle.controlHeight + 4
    color: MovieStyle.text; placeholderTextColor: MovieStyle.muted
    selectionColor: MovieStyle.accent; selectedTextColor: MovieStyle.accentText
    font.family: MovieStyle.fontFamily; font.pixelSize: MovieStyle.fontSize
    leftPadding: 12; rightPadding: 12
    selectByMouse: true
    inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
    background: Rectangle {
        radius: MovieStyle.controlRadius
        color: "#c0141117"
        border.width: 1
        border.color: root.activeFocus ? MovieStyle.accent : MovieStyle.border
    }
}
