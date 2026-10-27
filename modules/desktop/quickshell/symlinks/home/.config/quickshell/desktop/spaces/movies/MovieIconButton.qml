import "../../ui" as Desktop
import QtQuick

MovieButton {
    id: root

    property string hint: text
    property color iconColor: MovieStyle.muted

    implicitWidth: MovieStyle.controlHeight
    implicitHeight: MovieStyle.controlHeight
    padding: 9
    Accessible.name: text

    Desktop.PassiveToolTip {
        target: root
        text: root.hint
        maximumLineCount: 20
    }

    contentItem: MovieIcon {
        name: root.iconName
        color: root.hovered || root.highlighted || root.visualFocus ? MovieStyle.text : root.iconColor
    }
}
