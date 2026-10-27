pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../ui"
import "../ui/Models.js" as Models
import "disks"

DrawerPage {
    id: root
    property var service: DisksService
    property Popup openOptions: null
    readonly property bool canAct: active && service.loaded && !service.busy && !service.closing
    property var unlockVolume: null
    readonly property alias unlockPopup: unlock
    ListModel {
        id: drivesModel
        dynamicRoles: true
    }
    function sync(): void {
        Models.sync(drivesModel, service.state.drives, "key");
        if (unlockVolume && !service.state.drives.some(d => d.volumes.some(v => v.key === unlockVolume.key && v.identity === unlockVolume.identity && v.locked)))
            unlock.close();
    }
    function bytes(value): string {
        if (value === null || value === undefined)
            return qsTr("Unknown");
        const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
        let n = Math.max(0, Number(value)), i = 0;
        while (n >= 1024 && i < units.length - 1) {
            n /= 1024;
            i++;
        }
        return n.toLocaleString(Qt.locale(), "f", i && n < 10 ? 1 : 0) + " " + units[i];
    }
    function openLocation(location: string): void {
        Apps.launch(["dolphin", "--", location]);
        closeRequested();
    }
    function showUnlock(record): void {
        if (openOptions)
            openOptions.close();
        unlockVolume = record;
        passphrase.clear();
        unlock.open();
    }
    function volumeAction(record, action: string): void {
        if (action === "unlock")
            showUnlock(record);
        else
            service.change(record, action);
    }
    function submitUnlock(): void {
        if (!canAct || !passphrase.text.length || !unlockVolume)
            return;
        service.change(unlockVolume, "unlock", passphrase.text);
        unlock.close();
    }
    Connections {
        target: root.service
        function onStateChanged(): void {
            root.sync();
        }
    }
    Component.onCompleted: {
        sync();
        service.observe(root, active);
    }
    Component.onDestruction: service.observe(root, false)
    onActiveChanged: {
        service.observe(root, active);
        if (!active) {
            unlock.close();
            cleanup.closePopup();
            if (openOptions)
                openOptions.close();
        }
    }
    escapeHandler: cleanup.popupOpen ? (() => cleanup.closePopup()) : unlock.visible ? (() => unlock.close()) : openOptions ? (() => openOptions.close()) : null
    headerActions: RowLayout {
        spacing: 4
        IconButton {
            objectName: "disksUsage"
            iconName: "folder-search"
            text: qsTr("Scan largest directories")
            enabled: root.service.state.analyzerAvailable ?? false
            hint: enabled ? qsTr("Open Filelight") : qsTr("Install filelight to analyze directory sizes.")
            onClicked: {
                Apps.launch(["filelight"]);
                root.closeRequested();
            }
        }
        IconButton {
            objectName: "disksEditor"
            iconName: "pencil"
            text: qsTr("Open Partition Manager")
            enabled: root.service.state.editorAvailable
            hint: enabled ? qsTr("Partitioning, formatting and advanced filesystem operations") : qsTr("Install partitionmanager to open the partition editor.")
            onClicked: {
                Apps.launch(["partitionmanager"]);
                root.closeRequested();
            }
        }
        IconButton {
            objectName: "disksRefresh"
            iconName: "refresh-cw"
            text: qsTr("Refresh storage")
            enabled: !root.service.busy && !root.service.closing
            onClicked: root.service.refresh()
        }
    }
    component Note: ShellText {
        Layout.fillWidth: true
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
    component ActionError: RowLayout {
        required property string targetKey
        Layout.fillWidth: true
        spacing: 4
        visible: root.service.errorKey === targetKey && root.service.actionError !== ""
        Note {
            text: root.service.actionError
            color: Theme.danger
        }
        IconButton {
            iconName: "x"
            text: qsTr("Dismiss storage error")
            onClicked: root.service.dismissError()
        }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        RowLayout {
            visible: !root.service.loaded && root.service.busy
            BusySpinner {
                implicitWidth: 16
                implicitHeight: 16
            }
            Note {
                text: qsTr("Loading storage devices…")
            }
        }
        Note {
            objectName: "disksStatusError"
            visible: root.service.statusError !== ""
            text: root.service.statusError
            color: Theme.danger
        }
        ActionError {
            targetKey: root.service.errorKey
            visible: root.service.actionError !== "" && !root.service.state.drives.some(d => d.key === targetKey || d.volumes.some(v => v.key === targetKey))
        }
        Note {
            visible: root.service.message !== ""
            text: root.service.message
            color: Theme.success
        }
        DrawerColumn {
            objectName: "disksScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Note {
                visible: root.service.loaded && !drivesModel.count
                text: qsTr("No storage devices found.")
            }
            Repeater {
                model: drivesModel
                delegate: DriveCard {
                    service: root.service
                    formatBytes: root.bytes
                    canAct: root.canAct
                    onVolumeActionRequested: (record, action) => root.volumeAction(record, action)
                    onLocationRequested: location => root.openLocation(location)
                    onOptionsOpened: menu => {
                        if (root.openOptions && root.openOptions !== menu)
                            root.openOptions.close();
                        root.openOptions = menu;
                    }
                    onOptionsClosed: menu => {
                        if (root.openOptions === menu)
                            root.openOptions = null;
                    }
                }
            }
        }
        CleanupControl {
            id: cleanup
            Layout.fillWidth: true
            active: root.active
            onPopupOpened: {
                unlock.close();
                if (root.openOptions)
                    root.openOptions.close();
            }
        }
    }
    Popup {
        id: unlock
        objectName: "diskUnlockPopup"
        popupType: Popup.Item
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.max(0, Math.min(root.width, parent.width - 32))
        padding: 12
        margins: 16
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Surface {
            color: Theme.background
            radius: Theme.controlRadius
        }
        onOpened: passphrase.forceActiveFocus()
        onClosed: {
            passphrase.clear();
            root.unlockVolume = null;
        }
        contentItem: ColumnLayout {
            spacing: 12
            ShellText {
                text: qsTr("Unlock %1").arg(root.unlockVolume?.label ?? "")
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
                font.weight: Font.DemiBold
            }
            Note {
                text: root.unlockVolume?.device ?? ""
            }
            InputField {
                id: passphrase
                objectName: "diskPassphrase"
                Layout.fillWidth: true
                echoMode: TextInput.Password
                placeholderText: qsTr("Passphrase")
                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                Accessible.name: qsTr("Volume passphrase")
                onAccepted: root.submitUnlock()
            }
            ShellButton {
                objectName: "diskUnlockSubmit"
                text: qsTr("Unlock")
                Layout.fillWidth: true
                enabled: root.canAct && passphrase.text.length > 0
                onClicked: root.submitUnlock()
            }
        }
    }
}
