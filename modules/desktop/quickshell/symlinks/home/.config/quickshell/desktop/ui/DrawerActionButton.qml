pragma ComponentBehavior: Bound
import QtQuick

ShellButton {
    id: root
    implicitHeight: Math.max(48, implicitContentHeight + topPadding + bottomPadding)
    idleColor: Theme.surface
    contentItem: Item {
        readonly property int iconSpace: root.iconName ? 34 : 0
        implicitWidth: label.implicitWidth + iconSpace
        implicitHeight: Math.max(label.implicitHeight, root.iconName ? 22 : 0)
        Item {
            id: group
            anchors.centerIn: parent
            width: Math.min(parent.width, parent.implicitWidth)
            height: parent.height
            Icon {
                objectName: root.objectName + "Icon"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 22
                height: 22
                name: root.iconName
                visible: root.iconName !== ""
                color: root.highlighted ? Theme.accent : Theme.text
            }
            ShellText {
                id: label
                objectName: root.objectName + "Label"
                x: root.iconName ? 34 : 0
                width: Math.max(0, group.width - x)
                height: group.height
                text: root.text
                elide: Text.ElideRight
                textFormat: Text.PlainText
                font.weight: Font.Medium
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
}
