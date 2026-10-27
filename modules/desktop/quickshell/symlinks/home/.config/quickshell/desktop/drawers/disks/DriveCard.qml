pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"
import "../../ui/Models.js" as Models

Card {
    id: root
    required property var record
    required property var service
    required property var formatBytes
    property bool canAct: false
    property bool expanded: false
    property string observedIdentity: ""
    readonly property var primary: record.volumes.find(v => v.mounts.includes("/")) || record.volumes.find(v => v.mounts.length) || record.volumes[0] || null
    readonly property bool canExpand: record.volumes.some(v => v.mounts.length > 0)
    readonly property bool checkingHealth: service.pendingKey === record.key && service.pendingOp === "health"
    readonly property var health: service.healthFor(record)
    readonly property bool hasError: service.actionError !== "" && (service.errorKey === record.key || record.volumes.some(v => v.key === service.errorKey))
    readonly property string info: [record.label, record.size ? formatBytes(record.size) : qsTr("No media"), record.connection.toUpperCase(), record.removable ? qsTr("Removable") : qsTr("Internal"), record.ejectReason].filter(Boolean).join("\n")
    signal volumeActionRequested(var volume, string action)
    signal locationRequested(string location)
    signal optionsOpened(var menu)
    signal optionsClosed(var menu)
    ListModel {
        id: volumesModel
        dynamicRoles: true
    }
    function sync(): void {
        if (record.identity !== observedIdentity) {
            expanded = false;
            options.close();
            observedIdentity = record.identity;
        }
        if (!record.volumes.some(v => v.mounts.length > 0))
            expanded = false;
        Models.sync(volumesModel, record.volumes, "key");
    }
    onRecordChanged: sync()
    onCanExpandChanged: if (!canExpand)
        expanded = false
    Component.onCompleted: sync()
    Component.onDestruction: optionsClosed(options)
    objectName: "diskCard:" + record.key
    Layout.fillWidth: true
    implicitHeight: content.implicitHeight + 20
    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 10
        spacing: 6
        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            Icon {
                name: "hard-drive"
                Layout.preferredWidth: 18
                Layout.preferredHeight: 18
            }
            ShellButton {
                id: title
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                implicitWidth: 0
                implicitHeight: 30
                padding: 2
                enabled: root.canExpand
                opacity: 1
                text: root.record.label
                Accessible.name: qsTr("Volumes on %1").arg(text)
                onClicked: if (root.canExpand)
                    root.expanded = !root.expanded
                contentItem: ShellText {
                    text: title.text
                    font.weight: Font.DemiBold
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
                background: ButtonBackground {
                    idleColor: "transparent"
                    highlighted: title.hovered || title.visualFocus
                    pressed: title.down
                }
                PassiveToolTip {
                    target: title
                    text: root.info
                }
            }
            BusySpinner {
                visible: root.service.pendingKey === root.record.key
                running: visible
                implicitWidth: 16
                implicitHeight: 16
            }
            IconButton {
                id: healthButton
                readonly property alias menu: options
                objectName: "diskHealth:" + root.record.key
                iconName: "heart"
                text: qsTr("Health of %1").arg(root.record.label)
                enabled: root.record.healthSupported
                hint: enabled ? text : qsTr("Health reporting is unavailable for this drive.")
                iconColor: root.health?.warning ? Theme.warning : root.health ? Theme.success : Theme.muted
                implicitWidth: 28
                implicitHeight: 28
                padding: 5
                onClicked: {
                    if (options.visible)
                        options.close();
                    else {
                        options.open();
                        if (!root.health && root.canAct)
                            root.service.change(root.record, "health");
                    }
                }
                Popup {
                    id: options
                    objectName: "diskHealthPopup:" + root.record.key
                    popupType: Popup.Item
                    parent: healthButton
                    x: healthButton.width - width
                    y: healthButton.height
                    width: Math.min(340, root.width)
                    padding: 8
                    margins: 8
                    focus: true
                    height: Math.min(menuContent.implicitHeight + 16, (Overlay.overlay?.height ?? 700) - 24)
                    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
                    background: Surface {
                        color: Theme.background
                        radius: Theme.controlRadius
                    }
                    onAboutToShow: root.optionsOpened(options)
                    onClosed: root.optionsClosed(options)
                    contentItem: DrawerColumn {
                        ColumnLayout {
                            id: menuContent
                            Layout.fillWidth: true
                            spacing: 6
                            ShellText {
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                                color: Theme.muted
                                font.pixelSize: Theme.smallFontSize
                                text: [root.formatBytes(root.record.size), root.record.connection.toUpperCase(), root.record.removable ? qsTr("Removable") : qsTr("Internal")].filter(Boolean).join(" · ")
                            }
                            RowLayout {
                                visible: root.checkingHealth
                                Layout.fillWidth: true
                                BusySpinner {
                                    implicitWidth: 16
                                    implicitHeight: 16
                                }
                                ShellText {
                                    text: qsTr("Checking health…")
                                    color: Theme.muted
                                }
                            }
                            ShellText {
                                visible: !root.health && !root.checkingHealth
                                text: qsTr("No health information available yet.")
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                                color: Theme.muted
                            }
                            ShellText {
                                visible: root.service.errorKey === root.record.key && root.service.actionError !== ""
                                text: root.service.actionError
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                                color: Theme.danger
                                textFormat: Text.PlainText
                            }
                            ColumnLayout {
                                visible: root.health !== null
                                Layout.fillWidth: true
                                spacing: 4
                                ShellText {
                                    text: root.health?.summary ?? ""
                                    color: root.health?.warning ? Theme.warning : Theme.success
                                    Layout.fillWidth: true
                                    wrapMode: Text.Wrap
                                }
                                ShellText {
                                    Layout.fillWidth: true
                                    wrapMode: Text.Wrap
                                    color: Theme.muted
                                    font.pixelSize: Theme.smallFontSize
                                    text: root.health ? [root.health.temperature !== null ? root.health.temperature + " °C" : "", root.health.hours > 0 ? qsTr("%1 hours powered on").arg(root.health.hours) : "", root.health.badSectors !== null ? qsTr("%1 bad sectors").arg(root.health.badSectors) : "", root.health.detail, qsTr("Checked %1").arg(new Date(root.health.updated * 1000).toLocaleString(Qt.locale(), Locale.ShortFormat))].filter(Boolean).join(" · ") : ""
                                }
                            }
                            ShellButton {
                                objectName: "diskHealthRefresh:" + root.record.key
                                Layout.fillWidth: true
                                visible: root.record.healthSupported
                                text: root.health ? qsTr("Refresh health") : qsTr("Check health")
                                enabled: root.canAct
                                onClicked: root.service.change(root.record, "health")
                            }
                        }
                    }
                }
            }
            IconButton {
                objectName: "diskExpand:" + root.record.key
                iconName: root.expanded ? "chevron-up" : "chevron-down"
                text: root.expanded ? qsTr("Hide volumes and mount points") : qsTr("Show volumes and mount points")
                implicitWidth: 28
                implicitHeight: 28
                padding: 5
                enabled: root.canExpand
                visible: root.record.volumes.length > 0
                Accessible.checkable: true
                Accessible.checked: root.expanded
                onClicked: if (root.canExpand)
                    root.expanded = !root.expanded
            }
        }
        VolumeRow {
            visible: root.primary !== null
            record: root.primary || {
                key: "",
                label: "",
                device: "",
                fs: "",
                locked: false,
                canMount: false,
                canUnmount: false,
                mounts: [],
                capacity: null,
                free: null,
                size: 0,
                used: null,
                reason: "",
                capacityError: ""
            }
            formatBytes: root.formatBytes
            canAct: root.canAct
            pending: root.service.pendingKey === record.key
            onActionRequested: (record, action) => root.volumeActionRequested(record, action)
            onLocationRequested: location => root.locationRequested(location)
        }
        ColumnLayout {
            objectName: "diskDetails:" + root.record.key
            visible: root.expanded
            Layout.fillWidth: true
            spacing: 8
            Repeater {
                model: volumesModel
                delegate: VolumeRow {
                    showSummary: record.key !== root.primary?.key
                    showLocations: true
                    formatBytes: root.formatBytes
                    canAct: root.canAct
                    pending: root.service.pendingKey === record.key
                    onActionRequested: (record, action) => root.volumeActionRequested(record, action)
                    onLocationRequested: location => root.locationRequested(location)
                }
            }
        }
        ShellText {
            visible: root.primary === null
            text: root.record.size > 0 ? qsTr("No usable volumes") : qsTr("No media")
            Layout.fillWidth: true
            color: Theme.muted
            font.pixelSize: Theme.smallFontSize
        }
        RowLayout {
            visible: root.hasError
            Layout.fillWidth: true
            spacing: 4
            ShellText {
                text: root.service.actionError
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: Theme.danger
                font.pixelSize: Theme.smallFontSize
                textFormat: Text.PlainText
            }
            IconButton {
                iconName: "x"
                text: qsTr("Dismiss storage error")
                implicitWidth: 28
                implicitHeight: 28
                onClicked: root.service.dismissError()
            }
        }
    }
}
