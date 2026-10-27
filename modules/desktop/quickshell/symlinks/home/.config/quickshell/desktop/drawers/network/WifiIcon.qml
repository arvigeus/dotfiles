import "../../ui"
import "../../ui/NetworkIcons.js" as NetworkIcons
import QtQuick

Item {
    id: root

    property int strength: 100
    property bool secured: false
    property bool connected: false
    property color foreground: connected ? Theme.text : Theme.muted

    implicitWidth: 26
    implicitHeight: 26

    Icon {
        width: 22
        height: 22
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        name: NetworkIcons.wifi(root.strength)
        color: root.foreground
    }

    Rectangle {
        visible: root.secured
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: 13
        height: 13
        radius: 4
        color: Theme.background

        Icon {
            anchors.centerIn: parent
            width: 10
            height: 10
            name: "lock-keyhole"
            color: root.foreground
        }
    }
}
