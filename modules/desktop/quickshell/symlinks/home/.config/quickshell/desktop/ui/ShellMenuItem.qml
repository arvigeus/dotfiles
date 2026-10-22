pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

MenuItem {
    id: root
    property bool marked: checked
    implicitHeight: 36
    padding: 8
    spacing: 8
    hoverEnabled: true
    opacity: enabled ? 1 : 0.5
    indicator: Item {}
    contentItem: RowLayout {
        spacing: 8
        Icon {
            name: "check"
            opacity: root.marked ? 1 : 0
            Layout.preferredWidth: 16; Layout.preferredHeight: 16
            color: root.highlighted ? Theme.accent : Theme.text
        }
        ShellText {
            text: root.text
            Layout.fillWidth: true
            color: Theme.text
        }
    }
    background: ButtonBackground { highlighted: root.highlighted; pressed: root.down }
}
