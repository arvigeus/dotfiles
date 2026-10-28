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
        // Encode path segments: "#", "?" and "%" in file names are not URL syntax.
        source: !root.icon.length ? "" : root.icon.startsWith("/") ? "file://" + root.icon.split("/").map(encodeURIComponent).join("/") : Quickshell.iconPath(root.icon, true)
        // Layouts briefly have zero size during creation. Do not decode an SVG
        // at its possibly enormous intrinsic size before the row is laid out.
        sourceSize.width: Math.max(1, Math.ceil(width * Screen.devicePixelRatio))
        sourceSize.height: Math.max(1, Math.ceil(height * Screen.devicePixelRatio))
        fillMode: Image.PreserveAspectFit
    }
}
