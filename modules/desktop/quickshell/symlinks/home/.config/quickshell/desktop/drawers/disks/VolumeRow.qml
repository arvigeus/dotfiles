pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

ColumnLayout {
    id: root
    required property var record
    required property var formatBytes
    property bool canAct: false
    property bool pending: false
    property bool showSummary: true
    property bool showLocations: false
    readonly property string action: record.locked ? "unlock" : record.canMount ? "mount"
        : record.canUnmount ? "unmount" : ""
    signal actionRequested(var record, string action)
    signal locationRequested(string location)
    Layout.fillWidth: true; spacing: 4
    readonly property string details: [record.label, record.device, record.fs,
        record.locked ? qsTr("Locked") : !record.mounts.length ? qsTr("Not mounted") : "",
        record.reason, record.capacityError,
        record.capacity !== null ? qsTr("%1 free of %2").arg(formatBytes(record.free)).arg(formatBytes(record.capacity)) : formatBytes(record.size),
        record.mounts.join("\n")].filter(Boolean).join("\n")
    RowLayout {
        visible: root.showSummary; Layout.fillWidth: true; spacing: 6
        ShellButton {
            id: title
            objectName: "volumeTitle:" + root.record.key
            Layout.fillWidth: true; Layout.preferredWidth: 1; implicitWidth: 0
            implicitHeight: 28; padding: 0; opacity: 1
            text: root.record.label
            Accessible.name: root.record.mounts.length ? qsTr("Open %1 in the file manager").arg(text) : text
            onClicked: if (root.record.mounts.length) root.locationRequested(root.record.mounts[0])
            contentItem: RowLayout {
                spacing: 6
                Icon { visible: root.record.mounts.length > 0; name: "folder-open"; Layout.preferredWidth: 15; Layout.preferredHeight: 15; color: Theme.muted }
                ShellText { text: title.text; Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText; verticalAlignment: Text.AlignVCenter; font.weight: Font.Medium }
            }
            background: ButtonBackground { idleColor: "transparent"; highlighted: title.hovered || title.visualFocus; pressed: title.down }
            PassiveToolTip { target: title; text: root.details }
        }
        ShellText {
            text: root.record.free !== null ? qsTr("%1 free").arg(root.formatBytes(root.record.free)) : root.formatBytes(root.record.size)
            color: Theme.muted; font.pixelSize: Theme.smallFontSize
        }
        BusySpinner { visible: root.pending; running: visible; implicitWidth: 16; implicitHeight: 16 }
        IconButton {
            objectName: "volumeAction:" + root.record.key
            visible: root.action !== ""
            implicitWidth: 28; implicitHeight: 28; padding: 5
            iconName: root.action === "unlock" ? "lock-keyhole" : root.action === "mount" ? "hard-drive-download" : "hard-drive-upload"
            text: (root.action === "unlock" ? qsTr("Unlock %1") : root.action === "mount" ? qsTr("Mount %1") : qsTr("Unmount %1")).arg(root.record.label)
            enabled: root.canAct
            onClicked: root.actionRequested(root.record, root.action)
        }
    }
    Rectangle {
        objectName: "volumeUsage:" + root.record.key
        visible: root.showSummary && root.record.capacity !== null && root.record.capacity > 0
        Layout.fillWidth: true; implicitHeight: 4; radius: 2; color: Theme.raised
        readonly property real fraction: root.record.capacity ? Math.max(0, Math.min(1, root.record.used / root.record.capacity)) : 0
        Rectangle { width: parent.width * parent.fraction; height: parent.height; radius: parent.radius; color: parent.fraction >= 0.9 ? Theme.warning : Theme.accent }
    }
    Flow {
        visible: root.showLocations && root.record.mounts.length > 0
        Layout.fillWidth: true; spacing: 4
        Repeater {
            model: root.record.mounts
            delegate: ShellButton {
                id: location
                required property string modelData
                objectName: "volumeLocation:" + modelData
                text: modelData
                implicitWidth: Math.min(implicitContentWidth + 16, root.width)
                implicitHeight: 28; padding: 6
                contentItem: ShellText { text: location.text; font.pixelSize: Theme.smallFontSize; elide: Text.ElideMiddle; textFormat: Text.PlainText; verticalAlignment: Text.AlignVCenter }
                onClicked: root.locationRequested(modelData)
                PassiveToolTip { target: location; text: qsTr("Open %1 in the file manager").arg(location.modelData) }
            }
        }
    }
}
