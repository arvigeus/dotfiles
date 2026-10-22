pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../ui"

BarButton {
    id: root
    required property BarEntry entry
    readonly property bool hasBadge: entry.badgeReserveText !== "" || entry.badge !== ""
    objectName: entry.key + "Button"
    text: entry.title
    Accessible.description: entry.description
    enabled: entry.available
    selected: entry.attention
    implicitWidth: Math.max(Theme.controlHeight, contentItem.implicitWidth + leftPadding + rightPadding)
    implicitHeight: Theme.controlHeight
    padding: 0
    leftPadding: Theme.spacingMedium
    // The badge's reserved overhang already supplies the trailing space.
    rightPadding: hasBadge && entry.label === "" && entry.secondaryIconName === "" ? 0 : Theme.spacingMedium

    contentItem: RowLayout {
        spacing: Theme.spacingSmall
        Item {
            visible: root.entry.iconName !== "" || root.hasBadge
            implicitWidth: root.hasBadge ? Theme.iconSize + badge.implicitWidth / 2 : Theme.iconSize
            implicitHeight: root.hasBadge ? Theme.controlHeight : Theme.iconSize
            Layout.alignment: Qt.AlignVCenter

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                objectName: root.entry.key + "Icon"
                visible: root.entry.iconName !== ""
                name: root.entry.iconName
                color: root.entry.iconColor
                width: Theme.iconSize
                height: Theme.iconSize
            }
            StatusBadge {
                id: badge
                objectName: root.entry.key + "Badge"
                visible: root.hasBadge
                x: Theme.iconSize - width / 2
                y: parent.height - height
                text: root.entry.badge
                reserveText: root.entry.badgeReserveText || "99+"
                highlighted: root.entry.attention
            }
        }
        ShellText {
            visible: root.entry.label !== ""
            text: root.entry.label
            Layout.alignment: Qt.AlignVCenter
        }
        Icon {
            visible: root.entry.secondaryIconName !== ""
            name: root.entry.secondaryIconName
            color: root.entry.attention ? Theme.accent : Theme.text
            Layout.preferredWidth: Theme.iconSize
            Layout.preferredHeight: Theme.iconSize
            Layout.alignment: Qt.AlignVCenter
        }
    }
    PassiveToolTip { target: root; text: root.entry.description || root.text }
}
