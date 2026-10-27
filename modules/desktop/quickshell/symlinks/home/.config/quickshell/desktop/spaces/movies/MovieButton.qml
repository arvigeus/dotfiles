import "../../ui" as Desktop
import QtQuick
import QtQuick.Controls

Button {
    id: root

    property string iconName: ""
    property color idleColor: "transparent"
    readonly property int iconSlot: iconName ? 28 : 0

    highlighted: checked
    implicitWidth: implicitContentWidth + leftPadding + rightPadding
    implicitHeight: Math.max(MovieStyle.controlHeight, implicitContentHeight + 12)
    horizontalPadding: 12
    verticalPadding: 6
    hoverEnabled: true
    opacity: enabled ? 1 : 0.38

    contentItem: Item {
        implicitWidth: label.implicitWidth + root.iconSlot
        implicitHeight: Math.max(label.implicitHeight, root.iconName ? 20 : 0)

        MovieIcon {
            objectName: root.objectName + "Icon"
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            name: root.iconName
            visible: !!root.iconName
            width: 20
            height: 20
        }

        MovieText {
            id: label

            objectName: root.objectName + "Label"
            anchors.fill: parent
            anchors.leftMargin: root.iconSlot
            text: root.text
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    background: Rectangle {
        radius: MovieStyle.controlRadius
        color: root.down ? "#66e50914" : root.highlighted ? MovieStyle.accentSurface : root.hovered ? "#20ffffff" : root.idleColor
        border.width: root.visualFocus ? 2 : 0
        border.color: MovieStyle.accent

        Behavior on color {
            ColorAnimation {
                duration: 140
            }
        }
    }
}
