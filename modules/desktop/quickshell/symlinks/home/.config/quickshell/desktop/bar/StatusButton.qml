pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../ui"

BarButton {
    id: root
    required property BarEntry entry
    objectName: entry.key + "Button"
    text: entry.title
    Accessible.description: entry.description
    enabled: entry.available
    implicitWidth: Math.max(Theme.controlHeight, contentItem.implicitWidth + Theme.spacingMedium * 2)
    implicitHeight: Theme.controlHeight
    padding: 0
    leftPadding: Theme.spacingMedium
    rightPadding: Theme.spacingMedium

    contentItem: RowLayout {
        spacing: Theme.spacingSmall
        Icon {
            visible: root.entry.iconName !== ""
            name: root.entry.iconName
            color: root.entry.iconColor
            Layout.preferredWidth: Theme.iconSize
            Layout.preferredHeight: Theme.iconSize
            Layout.alignment: Qt.AlignVCenter
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
        ShellText {
            visible: root.entry.badge !== ""
            text: root.entry.badge
            color: root.entry.attention ? Theme.accent : Theme.muted
            font.pixelSize: Theme.smallFontSize
            Layout.alignment: Qt.AlignVCenter
        }
    }
    PassiveToolTip { target: root; text: ["wifi", "sound", "microphone"].includes(root.entry.key) ? root.entry.description : root.text }
}
