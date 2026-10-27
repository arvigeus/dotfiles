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
    function reconcile(): void {
        const wanted = new Set(items.map(row => row.id));
        for (let index = rows.count - 1; index >= 0; index--)
            if (!wanted.has(rows.get(index).key))
                rows.remove(index);
        for (let index = 0; index < items.length; index++) {
            const item = items[index];
            let current = index;
            while (current < rows.count && rows.get(current).key !== item.id)
                current++;
            if (current === rows.count)
                rows.insert(index, {
                    key: item.id,
                    record: item,
                    signature: JSON.stringify(item)
                });
            else {
                if (current !== index)
                    rows.move(current, index, 1);
                const signature = JSON.stringify(item);
                if (signature !== rows.get(index).signature) {
                    rows.setProperty(index, "record", item);
                    rows.setProperty(index, "signature", signature);
                }
            }
        }
    }
    onItemsChanged: reconcile()
    ListModel {
        id: rows
        dynamicRoles: true
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
            model: rows
            NotificationCard {
                required property string key
                Layout.fillWidth: true
                onDismissed: root.service.request("remove", key)
                onActionRequested: identifier => root.service.invoke(key, identifier)
            }
        }
    }
}
