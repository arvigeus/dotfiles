import QtQuick
import QtQuick.Controls

ScrollBar {
    id: root

    contentItem: Rectangle {
        implicitWidth: 4
        implicitHeight: 4
        radius: 2
        color: root.pressed ? MovieStyle.accent : "#80ffffff"
        opacity: root.active ? 1 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: 160
            }
        }
    }

    background: Item {}
}
