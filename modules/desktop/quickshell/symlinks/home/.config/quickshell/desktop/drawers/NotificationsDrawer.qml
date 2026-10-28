pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../ui"
import "notifications"

DrawerPage {
    id: root
    objectName: "notificationsDrawer"
    property var service: NotificationCenter
    readonly property var items: service.state.items
    headerActions: IconButton {
        objectName: "notificationsClear"
        iconName: "trash"
        text: qsTr("Clear notifications")
        enabled: root.items.length > 0
        onClicked: root.service.request("clear")
    }
    DrawerColumn {
        anchors.fill: parent
        RowLayout {
            Layout.fillWidth: true
            ShellText {
                text: qsTr("Do Not Disturb")
                Layout.fillWidth: true
            }
            ShellSwitch {
                objectName: "notificationsQuiet"
                text: qsTr("Do Not Disturb")
                checked: root.service.state.paused
                onToggled: root.service.request("pause", "", !root.service.state.paused)
            }
        }
        Item {
            Layout.fillWidth: true
            implicitHeight: Math.ceil(metrics.height)
            FontMetrics {
                id: metrics
                font: errorText.font
            }
            ShellText {
                id: errorText
                anchors.fill: parent
                text: root.service.error
                color: Theme.danger
                font.pixelSize: Theme.smallFontSize
                elide: Text.ElideRight
            }
            PassiveToolTip {
                target: errorText
                text: root.service.error
            }
        }
        ShellText {
            visible: !root.items.length
            text: qsTr("No notifications.")
            color: Theme.muted
        }
        Repeater {
            model: KeyedModel {
                values: root.items
                keyField: "id"
            }
            NotificationCard {
                required property var modelData
                record: modelData
                Layout.fillWidth: true
                onDismissed: root.service.request("remove", record.id)
                onActionRequested: identifier => root.service.invoke(record.id, identifier)
            }
        }
    }
}
