pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Bluetooth
import "../ui"
import "bluetooth"

DrawerPage {
    id: root
    property var service: BluetoothService
    property var bluetooth: Bluetooth
    property QtObject chosenAdapter: null
    property Popup informationPopup: null
    readonly property var adapters: bluetooth.adapters.values
    readonly property var adapter: adapters.includes(chosenAdapter) ? chosenAdapter : bluetooth.defaultAdapter ?? adapters[0] ?? null
    readonly property bool blocked: adapter?.state === BluetoothAdapterState.Blocked
    readonly property bool powerChanging: adapter?.state === BluetoothAdapterState.Enabling || adapter?.state === BluetoothAdapterState.Disabling
    readonly property bool canAct: active && !!adapter?.enabled
    readonly property bool pairing: !!service.pairingDevice
    readonly property var devices: (adapter ? [...adapter.devices.values] : []).sort((a, b) => group(a) - group(b) || a.name.localeCompare(b.name) || a.dbusPath.localeCompare(b.dbusPath))
    FontMetrics {
        id: metrics
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize
    }
    readonly property int actionWidth: Math.ceil(Math.max(...[qsTr("Connect"), qsTr("Disconnect"), qsTr("Pair"), qsTr("Connecting…"), qsTr("Disconnecting…"), qsTr("Pairing…")].map(text => metrics.advanceWidth(text)))) + 20
    function group(device): int {
        return device.connected ? 0 : device.paired ? 1 : 2;
    }
    function progress(device): string {
        if (service.pairingDevice === device)
            return service.pairingConnects ? qsTr("Connecting…") : qsTr("Pairing…");
        return device.state === BluetoothDeviceState.Connecting ? qsTr("Connecting…") : device.state === BluetoothDeviceState.Disconnecting ? qsTr("Disconnecting…") : "";
    }
    function release(): void {
        service.stopScan();
        service.cancel();
    }
    onActiveChanged: if (!active)
        release()
    Component.onDestruction: release()
    onAdapterChanged: informationPopup?.close()
    headerActions: RowLayout {
        spacing: 4
        ShellSwitch {
            objectName: "bluetoothPower"
            text: checked ? qsTr("Turn Bluetooth off") : qsTr("Turn Bluetooth on")
            checked: !!root.adapter?.enabled
            enabled: root.active && !!root.adapter && !root.blocked && !root.powerChanging
            onToggled: {
                const requested = checked;
                checked = Qt.binding(() => !!root.adapter?.enabled);
                root.adapter.enabled = requested;
            }
        }
        IconButton {
            id: information
            objectName: "bluetoothInfo"
            iconName: "info"
            text: qsTr("Bluetooth information")
            enabled: root.active
            checked: adapterInfo.visible
            onClicked: {
                if (adapterInfo.visible)
                    adapterInfo.close();
                else
                    adapterInfo.open();
            }
            InfoPopover {
                id: adapterInfo
                objectName: "bluetoothInfoPopup"
                button: information
                active: root.active
                onAboutToShow: root.informationPopup = adapterInfo
                onDismissed: if (root.informationPopup === adapterInfo)
                    root.informationPopup = null
                ShellText {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: Theme.muted
                    text: !root.adapter ? qsTr("No Bluetooth adapter found") : root.adapter.enabled ? qsTr("Bluetooth is on") : qsTr("Bluetooth is off")
                }
                InfoRow {
                    objectName: "bluetoothAdapterInfo"
                    label: qsTr("Adapter")
                    value: root.adapter?.name ?? ""
                }
                InfoRow {
                    objectName: "bluetoothInterfaceInfo"
                    label: qsTr("Interface")
                    value: root.adapter?.adapterId ?? ""
                }
            }
        }
        IconButton {
            objectName: "bluetoothScan"
            iconName: "refresh-cw"
            checked: !!root.adapter?.discovering
            // BlueZ lets only the client that started discovery stop it.
            enabled: root.active && (checked ? root.service.scanning && root.service.scanAdapter === root.adapter : root.canAct && !root.pairing)
            iconColor: checked ? Theme.accent : Theme.muted
            text: checked ? qsTr("Stop searching") : qsTr("Search for devices")
            onClicked: checked ? root.service.stopScan() : root.service.startScan(root.adapter)
        }
        IconButton {
            objectName: "bluetoothEdit"
            iconName: "pencil"
            text: qsTr("Bluetooth settings")
            onClicked: {
                Apps.launch(["blueman-manager"]);
                root.closeRequested();
            }
        }
    }
    escapeHandler: informationPopup ? (() => informationPopup.close()) : pairing && !service.pairingConnects ? (() => service.cancel()) : null
    function icon(device): string {
        if (/headset|headphone/.test(device.icon))
            return "headphones";
        if (/audio/.test(device.icon))
            return "speaker";
        if (/keyboard/.test(device.icon))
            return "keyboard";
        if (/computer/.test(device.icon))
            return "monitor";
        return "bluetooth";
    }
    component Note: ShellText {
        Layout.fillWidth: true
        font.pixelSize: Theme.smallFontSize
        color: Theme.muted
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gap
        RowLayout {
            visible: root.service.error !== "" && !root.devices.some(d => d.dbusPath === root.service.errorKey)
            Layout.fillWidth: true
            Note {
                objectName: "bluetoothError"
                text: root.service.error
                color: Theme.danger
            }
            IconButton {
                iconName: "x"
                text: qsTr("Dismiss Bluetooth error")
                onClicked: root.service.error = ""
            }
        }
        DrawerColumn {
            Layout.fillWidth: true
            Layout.fillHeight: true
            RowLayout {
                Layout.fillWidth: true
                visible: !root.adapter || root.blocked || root.powerChanging || !!root.adapter.discovering
                Note {
                    objectName: "bluetoothAdapterState"
                    text: !root.adapter ? qsTr("No Bluetooth adapter found") : root.blocked ? qsTr("Bluetooth is blocked by rfkill.") : root.powerChanging ? qsTr("Changing Bluetooth power…") : qsTr("Searching…")
                }
                BusySpinner {
                    implicitWidth: 16
                    implicitHeight: 16
                    visible: !!root.adapter && !root.blocked && (root.powerChanging || root.adapter.discovering)
                    running: visible && root.active
                }
            }
            ShellChoice {
                objectName: "bluetoothAdapter"
                Layout.fillWidth: true
                visible: root.adapters.length > 1
                enabled: root.active
                model: root.adapters.map(a => a.name || a.adapterId)
                currentIndex: root.adapters.indexOf(root.adapter)
                onActivated: index => {
                    root.service.stopScan();
                    root.chosenAdapter = root.adapters[index];
                }
            }
            Note {
                visible: !!root.adapter && !root.adapter.enabled && !root.blocked
                text: qsTr("Turn Bluetooth on to connect devices.")
            }
            Repeater {
                model: ScriptModel {
                    values: root.devices
                }
                delegate: ColumnLayout {
                    id: entry
                    required property int index
                    required property var modelData
                    readonly property var device: modelData
                    readonly property string key: device.dbusPath
                    readonly property string progress: root.progress(device)
                    readonly property bool pairingThis: root.service.pairingDevice === device
                    readonly property var prompt: pairingThis ? root.service.prompt : null
                    readonly property bool inputRequired: ["RequestPinCode", "RequestPasskey"].includes(prompt?.kind)
                    readonly property bool inlineActions: width >= 420
                    Layout.fillWidth: true
                    spacing: 6
                    ShellText {
                        visible: entry.index <= 0 || root.group(root.devices[entry.index - 1]) !== root.group(entry.device)
                        text: [qsTr("Connected"), qsTr("Paired devices"), qsTr("Available devices")][root.group(entry.device)]
                        topPadding: 10
                        bottomPadding: 2
                        font.weight: Font.DemiBold
                    }
                    Card {
                        Layout.fillWidth: true
                        implicitHeight: card.implicitHeight + 24
                        Item {
                            id: battery
                            objectName: "bluetoothBattery:" + entry.key
                            readonly property bool available: entry.device.batteryAvailable
                            readonly property int level: Math.round(Math.max(0, Math.min(1, entry.device.battery)) * 100)
                            readonly property string description: available ? qsTr("Battery: %1%").arg(level) : qsTr("Battery level not reported")
                            // The hover target shares the card's existing left padding.
                            x: 0
                            width: 12
                            height: Theme.controlHeight
                            y: card.y + summary.y + deviceIcon.y + (deviceIcon.height - height) / 2
                            Accessible.role: Accessible.ProgressBar
                            Accessible.name: description + " · " + entry.device.name
                            Rectangle {
                                objectName: "bluetoothBatteryTrack:" + entry.key
                                anchors.centerIn: parent
                                width: 3
                                height: 20
                                radius: 1.5
                                visible: battery.available
                                color: Theme.border
                                Rectangle {
                                    objectName: "bluetoothBatteryFill:" + entry.key
                                    anchors {
                                        left: parent.left
                                        right: parent.right
                                        bottom: parent.bottom
                                    }
                                    height: Math.max(1, parent.height * battery.level / 100)
                                    radius: 1.5
                                    color: battery.level <= 15 ? Theme.warning : Theme.muted
                                }
                            }
                            PassiveToolTip {
                                target: battery
                                text: battery.description
                            }
                        }
                        ColumnLayout {
                            id: card
                            anchors {
                                left: parent.left
                                right: parent.right
                                top: parent.top
                                margins: 12
                            }
                            spacing: 8
                            GridLayout {
                                id: summary
                                Layout.fillWidth: true
                                columns: entry.inlineActions ? 4 : 3
                                columnSpacing: 8
                                rowSpacing: 8
                                Icon {
                                    id: deviceIcon
                                    name: root.icon(entry.device)
                                    Layout.preferredWidth: 22
                                    Layout.preferredHeight: 22
                                    Layout.row: 0
                                    Layout.column: 0
                                }
                                ColumnLayout {
                                    Layout.row: 0
                                    Layout.column: 1
                                    Layout.minimumWidth: 0
                                    Layout.columnSpan: entry.inlineActions ? 1 : 2
                                    Layout.fillWidth: true
                                    spacing: 2
                                    ShellText {
                                        id: deviceName
                                        objectName: "bluetoothName:" + entry.key
                                        text: entry.device.name
                                        textFormat: Text.PlainText
                                        Layout.fillWidth: true
                                        elide: Text.ElideRight
                                        font.weight: Font.DemiBold
                                        PassiveToolTip {
                                            target: deviceName
                                            text: entry.device.name + "\n" + entry.device.address
                                        }
                                    }
                                    Note {
                                        objectName: "bluetoothState:" + entry.key
                                        visible: entry.device.blocked
                                        text: qsTr("Blocked in Bluetooth settings")
                                    }
                                }
                                ShellButton {
                                    id: deviceAction
                                    objectName: "bluetoothAction:" + entry.key
                                    Layout.row: entry.inlineActions ? 0 : 1
                                    Layout.column: entry.inlineActions ? 2 : 0
                                    Layout.columnSpan: entry.inlineActions ? 1 : entry.device.paired ? 2 : 3
                                    Layout.fillWidth: !entry.inlineActions
                                    Layout.minimumWidth: root.actionWidth
                                    Layout.preferredWidth: root.actionWidth
                                    enabled: root.canAct && !entry.device.blocked && !entry.progress && (entry.device.paired || !root.pairing)
                                    opacity: entry.progress || enabled ? 1 : 0.45
                                    text: entry.progress || (entry.device.connected ? qsTr("Disconnect") : entry.device.paired ? qsTr("Connect") : qsTr("Pair"))
                                    Accessible.name: (entry.progress || entry.device.paired ? text : qsTr("Pair and connect")) + " · " + entry.device.name
                                    onClicked: {
                                        if (entry.device.connected)
                                            root.service.disconnect(entry.device);
                                        else if (entry.device.paired)
                                            root.service.connect(entry.device);
                                        else
                                            root.service.pair(entry.device);
                                    }
                                    PassiveToolTip {
                                        target: deviceAction
                                        text: (entry.device.paired ? deviceAction.text : qsTr("Pair and connect")) + " · " + entry.device.name + "\n" + entry.device.address
                                    }
                                }
                                HoldButton {
                                    id: forgetButton
                                    objectName: "bluetoothForget:" + entry.key
                                    text: qsTr("Hold to forget %1").arg(entry.device.name)
                                    Accessible.name: text
                                    implicitWidth: Theme.controlHeight
                                    implicitHeight: Theme.controlHeight
                                    horizontalPadding: 8
                                    verticalPadding: 8
                                    idleColor: "transparent"
                                    contentItem: Icon {
                                        name: "trash"
                                        color: forgetButton.hovered || forgetButton.visualFocus ? Theme.accent : Theme.muted
                                    }
                                    Layout.row: entry.inlineActions ? 0 : 1
                                    Layout.column: entry.inlineActions ? 3 : 2
                                    Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                                    visible: entry.device.paired
                                    enabled: root.canAct && !entry.pairingThis
                                    armed: root.active
                                    onConfirmed: root.service.forget(entry.device)
                                }
                            }
                            ColumnLayout {
                                objectName: "bluetoothPrompt:" + entry.key
                                visible: !!entry.prompt
                                Layout.fillWidth: true
                                spacing: 8
                                Note {
                                    text: entry.prompt?.kind === "RequestConfirmation" ? qsTr("Does this code match the one on your device?") : entry.prompt?.kind.startsWith("Display") ? qsTr("Type this code on your device, then press Enter.") : entry.prompt?.kind === "RequestPinCode" ? qsTr("Enter the device’s PIN.") : entry.prompt?.kind === "RequestPasskey" ? qsTr("Enter the passkey shown on your device.") : qsTr("Allow pairing with this device?")
                                }
                                ShellText {
                                    objectName: "bluetoothPasskey:" + entry.key
                                    visible: !!entry.prompt?.code
                                    text: entry.prompt?.code ?? ""
                                    font.family: Theme.monospaceFamily
                                    font.pixelSize: 26
                                    font.letterSpacing: 3
                                }
                                Note {
                                    visible: entry.prompt?.kind === "DisplayPasskey"
                                    text: qsTr("%1 of 6 digits entered").arg(entry.prompt?.entered ?? 0)
                                }
                                InputField {
                                    id: codeInput
                                    objectName: "bluetoothPin:" + entry.key
                                    visible: entry.inputRequired
                                    Layout.fillWidth: true
                                    maximumLength: entry.prompt?.kind === "RequestPasskey" ? 6 : 16
                                    placeholderText: entry.prompt?.kind === "RequestPasskey" ? qsTr("Passkey") : qsTr("PIN")
                                    Accessible.name: placeholderText
                                    inputMethodHints: entry.prompt?.kind === "RequestPasskey" ? Qt.ImhDigitsOnly : Qt.ImhNone
                                    onAccepted: if (text.length)
                                        root.service.respond(true, text)
                                    onVisibleChanged: if (visible && root.active)
                                        Qt.callLater(() => {
                                            if (visible)
                                                forceActiveFocus();
                                        })
                                    Connections {
                                        target: root.service
                                        function onPromptChanged(): void {
                                            codeInput.clear();
                                        }
                                    }
                                }
                            }
                            RowLayout {
                                visible: root.service.error !== "" && root.service.errorKey === entry.key
                                Layout.fillWidth: true
                                Note {
                                    text: root.service.error
                                    color: Theme.danger
                                }
                                IconButton {
                                    iconName: "x"
                                    text: qsTr("Dismiss Bluetooth error")
                                    onClicked: root.service.error = ""
                                }
                            }
                            RowLayout {
                                visible: entry.pairingThis && !root.service.pairingConnects
                                Layout.fillWidth: true
                                spacing: 8
                                ShellButton {
                                    objectName: "bluetoothSubmit:" + entry.key
                                    Layout.fillWidth: true
                                    visible: !!entry.prompt && !entry.prompt.kind.startsWith("Display")
                                    enabled: root.active && !!root.adapter?.enabled && (!entry.inputRequired || codeInput.text.length > 0)
                                    text: entry.inputRequired ? qsTr("Submit") : qsTr("Confirm")
                                    onClicked: root.service.respond(true, codeInput.text)
                                }
                                ShellButton {
                                    objectName: "bluetoothCancel:" + entry.key
                                    Layout.fillWidth: true
                                    text: entry.prompt && !entry.prompt.kind.startsWith("Display") ? qsTr("Reject") : qsTr("Cancel pairing")
                                    onClicked: entry.prompt && !entry.prompt.kind.startsWith("Display") ? root.service.respond(false, "") : root.service.cancel()
                                }
                            }
                        }
                    }
                }
            }
            Note {
                visible: !!root.adapter?.enabled && !root.devices.length
                text: root.adapter?.discovering ? qsTr("Searching for nearby devices…") : qsTr("No devices yet. Put your device in pairing mode, then search.")
            }
        }
    }
}
