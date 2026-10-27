pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls

Switch {
    id: root
    implicitWidth: 38
    implicitHeight: Theme.controlHeight
    padding: 0
    hoverEnabled: true
    Accessible.name: text
    indicator: Rectangle {
        anchors.centerIn: parent
        implicitWidth: 38
        implicitHeight: 22
        radius: height / 2
        color: root.checked ? Theme.accent : Theme.border
        opacity: root.enabled ? 1 : 0.45
        Rectangle {
            x: root.checked ? parent.width - width - 3 : 3
            y: 3
            width: 16
            height: 16
            radius: 8
            color: root.checked ? Theme.accentText : Theme.text
        }
    }
    contentItem: Item {}
    background: ButtonBackground {
        idleColor: "transparent"
        highlighted: root.visualFocus
        pressed: root.down
    }
    PassiveToolTip {
        target: root
    }
}
