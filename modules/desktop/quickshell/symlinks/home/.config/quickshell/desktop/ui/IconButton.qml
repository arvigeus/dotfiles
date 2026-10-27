import QtQuick
import QtQuick.Controls

Button {
    id: root
    property string iconName: ""
    property string hint: text
    property color iconColor: Theme.muted
    property bool highlightChecked: true
    implicitWidth: Theme.controlHeight
    implicitHeight: Theme.controlHeight
    padding: 8
    hoverEnabled: true
    Accessible.name: text
    opacity: enabled ? 1 : 0.4
    contentItem: Icon {
        name: root.iconName
        color: root.hovered || root.visualFocus ? Theme.accent : root.iconColor
    }
    background: ButtonBackground {
        highlighted: root.hovered || root.visualFocus || (root.highlightChecked && root.checked)
        pressed: root.down
    }
    PassiveToolTip {
        target: root
        text: root.hint
        maximumLineCount: 20
    }
}
