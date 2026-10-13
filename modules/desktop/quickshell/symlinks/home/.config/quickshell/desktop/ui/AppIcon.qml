import QtQuick
import QtQuick.Window
import Quickshell

Item {
    id: root

    property string icon: ""

    implicitWidth: Theme.iconSize
    implicitHeight: Theme.iconSize

    Image {
        anchors.fill: parent
        source: !root.icon.length ? "" : root.icon.startsWith("/")
            ? "file://" + root.icon : Quickshell.iconPath(root.icon, true)
        sourceSize.width: Math.ceil(width * Screen.devicePixelRatio)
        sourceSize.height: Math.ceil(height * Screen.devicePixelRatio)
        fillMode: Image.PreserveAspectFit
    }
}
