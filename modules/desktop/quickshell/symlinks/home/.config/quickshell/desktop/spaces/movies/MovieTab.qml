import QtQuick

MovieButton {
    id: root
    horizontalPadding: 14
    background: Rectangle {
        radius: MovieStyle.controlRadius
        color: root.down ? "#30e50914" : root.hovered ? "#15ffffff" : "transparent"
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
            anchors.leftMargin: 12; anchors.rightMargin: 12
            height: 3; radius: 1.5
            color: MovieStyle.accent
            visible: root.highlighted || root.visualFocus
        }
    }
}
