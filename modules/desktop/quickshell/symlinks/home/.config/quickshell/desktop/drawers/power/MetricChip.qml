import "../../ui"
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Button {
    id: root

    property string iconName: ""
    property string label: ""
    property string value: ""
    property string detail: ""
    property color valueColor: Theme.text

    Layout.fillWidth: true
    implicitWidth: contentItem.implicitWidth + 12
    implicitHeight: 34
    padding: 6
    hoverEnabled: true
    activeFocusOnTab: false
    Accessible.role: Accessible.StaticText
    Accessible.name: label + ": " + value
    Accessible.description: detail

    PassiveToolTip {
        target: root
        text: root.label + ": " + root.value + (root.detail ? "\n" + root.detail : "")
    }

    contentItem: RowLayout {
        spacing: 7

        Icon {
            name: root.iconName
            color: Theme.muted
            Layout.preferredWidth: 17
            Layout.preferredHeight: 17
        }

        ShellText {
            text: root.value
            color: root.valueColor
            font.pixelSize: Theme.smallFontSize
            Layout.fillWidth: true
            elide: Text.ElideRight
        }
    }

    background: Item {}
}
