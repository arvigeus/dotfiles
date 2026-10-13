import QtQuick
import QtQuick.Window
import QtQuick.Effects

Item {
    id: root

    property string name: ""
    property color color: Theme.text
    readonly property int status: image.status

    implicitWidth: Theme.iconSize
    implicitHeight: Theme.iconSize

    Image {
        id: image
        anchors.fill: parent
        visible: false
        source: root.name.length ? Qt.resolvedUrl("../icons/" + root.name + ".svg") : ""
        sourceSize.width: Math.ceil(width * Screen.devicePixelRatio)
        sourceSize.height: Math.ceil(height * Screen.devicePixelRatio)
        fillMode: Image.PreserveAspectFit
    }

    MultiEffect {
        anchors.fill: parent
        source: image
        // currentColor renders black; brighten before Qt's luminance-based tint.
        brightness: 1
        colorization: 1
        colorizationColor: root.color
    }
}
