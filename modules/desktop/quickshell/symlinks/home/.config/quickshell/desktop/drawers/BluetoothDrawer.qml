pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../ui"
import "audio"
import "network"
import "bluetooth"
import "network/Models.js" as Models

DrawerPage {
    id: root
    property var service: BluetoothService
    property string adapterKey: ""
    property Popup informationPopup: null
    readonly property var adapter: service.state.adapters.find(a => a.key === adapterKey) ?? null
    readonly property var devices: service.state.devices.filter(d => d.adapter === adapterKey)
    readonly property bool canAct: active && service.loaded && service.state.available && !service.busy
    readonly property int actionWidth: Math.ceil(Math.max(connectMetrics.advanceWidth, disconnectMetrics.advanceWidth, pairMetrics.advanceWidth,
        connectingMetrics.advanceWidth, disconnectingMetrics.advanceWidth, pairingMetrics.advanceWidth, forgettingMetrics.advanceWidth)) + 20
    TextMetrics { id: connectMetrics; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; text: qsTr("Connect") }
    TextMetrics { id: disconnectMetrics; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; text: qsTr("Disconnect") }
    TextMetrics { id: pairMetrics; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; text: qsTr("Pair") }
    TextMetrics { id: connectingMetrics; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; text: qsTr("Connecting…") }
    TextMetrics { id: disconnectingMetrics; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; text: qsTr("Disconnecting…") }
    TextMetrics { id: pairingMetrics; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; text: qsTr("Pairing…") }
    TextMetrics { id: forgettingMetrics; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; text: qsTr("Forgetting…") }
    headerActions: RowLayout {
        spacing: 4
        ShellSwitch {
            objectName: "bluetoothPower"
            text: checked ? qsTr("Turn Bluetooth off") : qsTr("Turn Bluetooth on")
            checked: !!root.adapter?.powered
            enabled: root.canAct && !!root.adapter
            onToggled: {
                const requested = checked;
                checked = Qt.binding(() => !!root.adapter?.powered);
                root.service.run("power", root.adapter, {enabled: requested});
            }
        }
        AudioIconButton {
            id: information
            objectName: "bluetoothInfo"; iconName: "info"; text: qsTr("Bluetooth information")
            enabled: root.active; checked: adapterInfo.visible
            onClicked: { if (adapterInfo.visible) adapterInfo.close(); else adapterInfo.open(); }
            InfoPopover {
                id: adapterInfo
                objectName: "bluetoothInfoPopup"; button: information; active: root.active
                onAboutToShow: root.informationPopup = adapterInfo
                onDismissed: if (root.informationPopup === adapterInfo) root.informationPopup = null
                ShellText {
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted
                    text: !root.service.loaded ? qsTr("Reading Bluetooth status…")
                        : !root.adapter ? qsTr("No Bluetooth adapter found")
                        : root.adapter.powered ? qsTr("Bluetooth is on") : qsTr("Bluetooth is off")
                }
                InfoRow { objectName: "bluetoothAdapterInfo"; label: qsTr("Adapter"); value: root.adapter?.name ?? "" }
                InfoRow { objectName: "bluetoothInterfaceInfo"; label: qsTr("Interface"); value: root.adapter?.key.split("/").pop() ?? "" }
                InfoRow { objectName: "bluetoothAddressInfo"; label: qsTr("Address"); value: root.adapter?.address ?? "" }
            }
        }
        AudioIconButton {
            objectName: "bluetoothScan"; iconName: "refresh-cw"
            enabled: root.active && (!!root.service.scanning || (root.canAct && !!root.adapter?.powered))
            checked: root.service.scanning !== ""
            iconColor: checked ? Theme.accent : Theme.muted
            text: checked ? qsTr("Stop searching") : qsTr("Search for devices")
            onClicked: root.service.scanning ? root.service.stopScan() : root.service.run("scan", root.adapter)
        }
        AudioIconButton {
            objectName: "bluetoothEdit"; iconName: "pencil"; text: qsTr("Bluetooth settings")
            onClicked: { Quickshell.execDetached(["blueman-manager"]); root.closeRequested(); }
        }
    }
    ListModel { id: deviceModel; dynamicRoles: true }
    function sync(): void {
        if (!service.state.adapters.some(a => a.key === adapterKey)) adapterKey = service.state.adapters[0]?.key ?? "";
        const current = service.state.devices.filter(d => d.adapter === adapterKey);
        Models.sync(deviceModel, current, "key", false);
    }
    onAdapterKeyChanged: { informationPopup?.close(); Qt.callLater(root.sync); }
    Connections { target: root.service; function onStateChanged(): void { root.sync(); } }
    onActiveChanged: service.observe(root, active)
    Component.onCompleted: { sync(); service.observe(root, active); }
    Component.onDestruction: service.observe(root, false)
    escapeHandler: informationPopup ? (() => informationPopup.close())
        : service.pending === "pair" ? (() => service.cancel()) : null
    function icon(device): string {
        if (/headset|headphone/.test(device.icon)) return "headphones";
        if (/audio/.test(device.icon)) return "speaker";
        if (/keyboard/.test(device.icon)) return "keyboard";
        if (/computer/.test(device.icon)) return "monitor";
        return "bluetooth";
    }
    function progress(op): string {
        return ({pair: qsTr("Pairing…"), connect: qsTr("Connecting…"), disconnect: qsTr("Disconnecting…"),
                 forget: qsTr("Forgetting…"), power: qsTr("Changing Bluetooth power…"), scan: qsTr("Starting discovery…")})[op] || "";
    }
    component Note: ShellText {
        Layout.fillWidth: true; font.pixelSize: Theme.smallFontSize; color: Theme.muted
        wrapMode: Text.Wrap; textFormat: Text.PlainText
    }
    ColumnLayout {
        anchors.fill: parent; spacing: Theme.gap
        RowLayout {
            visible: root.service.error !== "" && !root.devices.some(d => d.key === root.service.errorKey); Layout.fillWidth: true
            Note { objectName: "bluetoothError"; text: root.service.error; color: Theme.danger }
            AudioIconButton { iconName: "x"; text: qsTr("Dismiss Bluetooth error"); onClicked: root.service.error = "" }
        }
        DrawerColumn {
            Layout.fillWidth: true; Layout.fillHeight: true
            RowLayout {
                Layout.fillWidth: true
                visible: !root.service.loaded || !root.service.state.available || !root.adapter
                    || !!root.service.scanning || ["power", "scan"].includes(root.service.pending)
                Note {
                    objectName: "bluetoothAdapterState"
                    text: !root.service.loaded ? qsTr("Reading Bluetooth status…")
                        : !root.service.state.available ? qsTr("Bluetooth service unavailable")
                        : !root.adapter ? qsTr("No Bluetooth adapter found")
                        : root.service.pending ? root.progress(root.service.pending) : qsTr("Searching…")
                }
                BusySpinner {
                    implicitWidth: 16; implicitHeight: 16
                    visible: !root.service.loaded || !!root.service.scanning || ["power", "scan"].includes(root.service.pending)
                    running: visible && root.active
                }
            }
            NetworkChoice {
                objectName: "bluetoothAdapter"; Layout.fillWidth: true
                visible: root.service.state.adapters.length > 1; enabled: root.canAct
                model: root.service.state.adapters; textRole: "name"
                currentIndex: root.service.state.adapters.findIndex(a => a.key === root.adapterKey)
                onActivated: {
                    root.service.stopScan();
                    root.adapterKey = root.service.state.adapters[currentIndex].key;
                }
            }
            Note { visible: !!root.adapter && !root.adapter.powered; text: qsTr("Turn Bluetooth on to connect devices.") }
            Repeater {
                model: deviceModel
                delegate: ColumnLayout {
                    id: entry
                    required property int index
                    required property var record
                    readonly property bool pending: root.service.busy && root.service.pendingKey === record.key
                    readonly property var prompt: root.service.prompt?.key === record.key ? root.service.prompt : null
                    readonly property bool inputRequired: ["RequestPinCode", "RequestPasskey"].includes(prompt?.kind)
                    readonly property bool inlineActions: width >= 420
                    Layout.fillWidth: true; spacing: 6
                    ShellText {
                        readonly property int group: entry.record.connected ? 0 : entry.record.paired ? 1 : 2
                        visible: entry.index <= 0 || (deviceModel.get(entry.index - 1)?.record?.connected ? 0 : deviceModel.get(entry.index - 1)?.record?.paired ? 1 : 2) !== group
                        text: group === 0 ? qsTr("Connected") : group === 1 ? qsTr("Paired devices") : qsTr("Available devices")
                        topPadding: 10; bottomPadding: 2; font.weight: Font.DemiBold
                    }
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: card.implicitHeight + 24
                        radius: Theme.controlRadius; color: Theme.surface
                        Item {
                            id: battery
                            objectName: "bluetoothBattery:" + entry.record.key
                            readonly property bool available: entry.record.battery >= 0
                            readonly property real level: Math.max(0, Math.min(100, entry.record.battery))
                            readonly property string description: available ? qsTr("Battery: %1%").arg(entry.record.battery)
                                : qsTr("Battery level not reported")
                            // The hover target shares the card's existing left padding.
                            x: 0; width: 12; height: Theme.controlHeight
                            y: card.y + summary.y + deviceIcon.y + (deviceIcon.height - height) / 2
                            Accessible.role: Accessible.ProgressBar
                            Accessible.name: description + " · " + entry.record.name
                            Rectangle {
                                objectName: "bluetoothBatteryTrack:" + entry.record.key
                                anchors.centerIn: parent; width: 3; height: 20; radius: 1.5
                                visible: battery.available; color: Theme.border
                                Rectangle {
                                    objectName: "bluetoothBatteryFill:" + entry.record.key
                                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                                    height: Math.max(1, parent.height * battery.level / 100)
                                    radius: 1.5; color: battery.level <= 15 ? Theme.warning : Theme.muted
                                }
                            }
                            PassiveToolTip { target: battery; text: battery.description }
                        }
                        ColumnLayout {
                            id: card
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
                            spacing: 8
                            GridLayout {
                                id: summary
                                Layout.fillWidth: true; columns: entry.inlineActions ? 4 : 3
                                columnSpacing: 8; rowSpacing: 8
                                Icon {
                                    id: deviceIcon
                                    name: root.icon(entry.record); Layout.preferredWidth: 22; Layout.preferredHeight: 22
                                    Layout.row: 0; Layout.column: 0
                                }
                                ColumnLayout {
                                    Layout.row: 0; Layout.column: 1; Layout.minimumWidth: 0
                                    Layout.columnSpan: entry.inlineActions ? 1 : 2
                                    Layout.fillWidth: true; spacing: 2
                                    ShellText {
                                        id: deviceName
                                        objectName: "bluetoothName:" + entry.record.key
                                        text: entry.record.name; textFormat: Text.PlainText
                                        Layout.fillWidth: true; elide: Text.ElideRight; font.weight: Font.DemiBold
                                        PassiveToolTip { target: deviceName; text: entry.record.name + "\n" + entry.record.address }
                                    }
                                    Note {
                                        objectName: "bluetoothState:" + entry.record.key
                                        visible: entry.record.blocked
                                        text: qsTr("Blocked in Bluetooth settings")
                                    }
                                }
                                ShellButton {
                                    id: deviceAction
                                    objectName: "bluetoothAction:" + entry.record.key
                                    Layout.row: entry.inlineActions ? 0 : 1
                                    Layout.column: entry.inlineActions ? 2 : 0
                                    Layout.columnSpan: entry.inlineActions ? 1 : entry.record.paired ? 2 : 3
                                    Layout.fillWidth: !entry.inlineActions
                                    Layout.minimumWidth: root.actionWidth
                                    Layout.preferredWidth: root.actionWidth
                                    enabled: root.canAct && !!root.adapter?.powered && !entry.record.blocked
                                    opacity: entry.pending || enabled ? 1 : 0.45
                                    text: entry.pending ? root.progress(root.service.pending) || qsTr("Working…")
                                        : entry.record.connected ? qsTr("Disconnect") : entry.record.paired ? qsTr("Connect") : qsTr("Pair")
                                    Accessible.name: (entry.pending || entry.record.paired ? text : qsTr("Pair and connect")) + " · " + entry.record.name
                                    onClicked: root.service.run(entry.record.connected ? "disconnect" : entry.record.paired ? "connect" : "pair", entry.record)
                                    PassiveToolTip {
                                        target: deviceAction
                                        text: (entry.record.paired ? deviceAction.text : qsTr("Pair and connect"))
                                            + " · " + entry.record.name + "\n" + entry.record.address
                                    }
                                }
                                HoldButton {
                                    id: forgetButton
                                    objectName: "bluetoothForget:" + entry.record.key
                                    text: qsTr("Hold to forget %1").arg(entry.record.name)
                                    Accessible.name: text
                                    implicitWidth: Theme.controlHeight; implicitHeight: Theme.controlHeight
                                    horizontalPadding: 8; verticalPadding: 8; idleColor: "transparent"
                                    contentItem: Icon { name: "trash"; color: forgetButton.hovered || forgetButton.visualFocus ? Theme.accent : Theme.muted }
                                    Layout.row: entry.inlineActions ? 0 : 1
                                    Layout.column: entry.inlineActions ? 3 : 2
                                    Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                                    visible: entry.record.paired
                                    enabled: root.canAct && !!root.adapter?.powered
                                    armed: root.active
                                    onConfirmed: root.service.run("forget", entry.record)
                                }
                            }
                            ColumnLayout {
                                objectName: "bluetoothPrompt:" + entry.record.key
                                visible: !!entry.prompt; Layout.fillWidth: true; spacing: 8
                                Note {
                                    text: entry.prompt?.kind === "RequestConfirmation" ? qsTr("Does this code match the one on your device?")
                                        : entry.prompt?.kind.startsWith("Display") ? qsTr("Type this code on your device, then press Enter.")
                                        : entry.prompt?.kind === "RequestPinCode" ? qsTr("Enter the device’s PIN.")
                                        : entry.prompt?.kind === "RequestPasskey" ? qsTr("Enter the passkey shown on your device.")
                                        : qsTr("Allow pairing with this device?")
                                }
                                ShellText {
                                    objectName: "bluetoothPasskey:" + entry.record.key
                                    visible: !!entry.prompt?.code; text: entry.prompt?.code ?? ""
                                    font.family: Theme.monospaceFamily; font.pixelSize: 26; font.letterSpacing: 3
                                }
                                Note {
                                    visible: entry.prompt?.kind === "DisplayPasskey"
                                    text: qsTr("%1 of 6 digits entered").arg(entry.prompt?.entered ?? 0)
                                }
                                InputField {
                                    id: codeInput
                                    objectName: "bluetoothPin:" + entry.record.key
                                    visible: entry.inputRequired
                                    Layout.fillWidth: true; maximumLength: entry.prompt?.kind === "RequestPasskey" ? 6 : 16
                                    placeholderText: entry.prompt?.kind === "RequestPasskey" ? qsTr("Passkey") : qsTr("PIN")
                                    Accessible.name: placeholderText
                                    inputMethodHints: entry.prompt?.kind === "RequestPasskey" ? Qt.ImhDigitsOnly : Qt.ImhNone
                                    onAccepted: if (text.length) root.service.respond(true, text)
                                    onVisibleChanged: if (visible && root.active) Qt.callLater(() => { if (visible) forceActiveFocus(); })
                                    Connections { target: root.service; function onPromptChanged(): void { codeInput.clear(); } }
                                }
                            }
                            RowLayout {
                                visible: root.service.error !== "" && root.service.errorKey === entry.record.key
                                Layout.fillWidth: true
                                Note { text: root.service.error; color: Theme.danger }
                                AudioIconButton { iconName: "x"; text: qsTr("Dismiss Bluetooth error"); onClicked: root.service.error = "" }
                            }
                            RowLayout {
                                visible: entry.pending && root.service.pending === "pair"
                                Layout.fillWidth: true; spacing: 8
                                ShellButton {
                                    objectName: "bluetoothSubmit:" + entry.record.key; Layout.fillWidth: true
                                    visible: !!entry.prompt && !entry.prompt.kind.startsWith("Display")
                                    enabled: root.active && !!root.adapter?.powered && (!entry.inputRequired || codeInput.text.length > 0)
                                    text: entry.inputRequired ? qsTr("Submit") : qsTr("Confirm")
                                    onClicked: root.service.respond(true, codeInput.text)
                                }
                                ShellButton {
                                    objectName: "bluetoothCancel:" + entry.record.key; Layout.fillWidth: true
                                    visible: entry.pending && root.service.pending === "pair"
                                    text: entry.prompt && !entry.prompt.kind.startsWith("Display") ? qsTr("Reject") : qsTr("Cancel pairing")
                                    onClicked: entry.prompt && !entry.prompt.kind.startsWith("Display") ? root.service.respond(false, "") : root.service.cancel()
                                }
                            }
                        }
                    }
                }
            }
            Note {
                visible: !!root.adapter?.powered && !deviceModel.count && root.service.loaded
                text: root.service.scanning ? qsTr("Searching for nearby devices…") : qsTr("No devices yet. Put your device in pairing mode, then search.")
            }
        }
    }
}
