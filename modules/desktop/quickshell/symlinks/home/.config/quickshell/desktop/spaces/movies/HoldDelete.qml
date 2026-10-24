import QtQuick
import QtQuick.Layouts
import "../../ui"
HoldButton {
    id: root
    property bool torrent: false
    property bool showLabel: false
    property string localHint: "Delete local file"
    signal activated()
    iconName: "trash-2"
    text: showLabel ? "Delete" : ""
    hint: torrent ? "Delete torrent and all its downloaded files" : root.localHint
    implicitWidth: showLabel ? 100 : MovieStyle.controlHeight
    onConfirmed: activated()
    contentItem: RowLayout {
        spacing: 6
        MovieIcon { name: root.iconName; color: MovieStyle.danger; Layout.preferredWidth: 20; Layout.preferredHeight: 20 }
        MovieText { visible: root.showLabel; text: root.text }
    }
    background: Rectangle {
        radius: MovieStyle.controlRadius
        color: root.down ? "#60e50914" : root.hovered || root.visualFocus ? "#30e50914" : "transparent"
        Rectangle {
            anchors.left: parent.left; anchors.bottom: parent.bottom
            width: parent.width * root.progress; height: 3; radius: 1
            color: MovieStyle.danger
        }
    }
}
