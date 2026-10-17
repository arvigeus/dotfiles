import QtQuick
import QtQuick.Controls

Button {
    id: root
    property string iconName: ""
    property color idleColor: Theme.raised
    highlighted: hovered || visualFocus || checked
    readonly property int iconSlot: iconName ? Theme.iconSize + 8 : 0
    implicitWidth: Math.max(implicitBackgroundWidth, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(Theme.controlHeight, implicitContentHeight + topPadding + bottomPadding)
    horizontalPadding: 10
    verticalPadding: 0
    hoverEnabled: true
    opacity: enabled ? 1 : 0.45
    contentItem: Item {
        implicitWidth: label.implicitWidth + root.iconSlot * 2
        implicitHeight: Math.max(label.implicitHeight, root.iconName ? Theme.iconSize : 0)
        Icon {
            objectName: root.objectName + "Icon"
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            name: root.iconName; visible: root.iconName !== ""
            color: root.highlighted ? Theme.accent : Theme.text
        }
        ShellText {
            id: label
            objectName: root.objectName + "Label"
            anchors.fill: parent
            anchors.leftMargin: root.iconSlot; anchors.rightMargin: root.iconSlot
            text: root.text; elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
    }
    background: ButtonBackground {
        idleColor: root.idleColor; highlighted: root.highlighted; pressed: root.down
    }
}
