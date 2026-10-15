pragma ComponentBehavior: Bound
import QtQuick
import "../ui"

Surface {
    id: root
    property list<BarEntry> entries
    signal drawerRequested(string key)
    implicitWidth: buttons.implicitWidth + Theme.spacingSmall * 2
    implicitHeight: Theme.controlHeight
    radius: Theme.pillRadius
    border.width: 0

    Row {
        id: buttons
        anchors.centerIn: parent
        spacing: 0
        Repeater {
            model: root.entries
            delegate: StatusButton {
                required property BarEntry modelData
                entry: modelData
                onClicked: root.drawerRequested(entry.key)
            }
        }
    }
}
