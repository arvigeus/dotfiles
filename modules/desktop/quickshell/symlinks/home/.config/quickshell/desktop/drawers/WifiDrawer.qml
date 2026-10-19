pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQml.Models
import Quickshell
import "../ui"
import "network"
import "network/Models.js" as Models

DrawerPage {
    id: root
    property var service: NetworkService
    property var selected: null
    property string passwordText: ""
    property bool showPassword: false
    property bool passwordRequired: false
    property var speedTest: SpeedTestService
    property var portsService: PortsService
    property var publicIp: PublicIpService
    property Popup informationPopup: null
    readonly property string localAddress: adapter?.connected ? (adapter.ipv4?.[0]
        ?? adapter.details?.match(/^IPv4: ([^/\s,]+)/m)?.[1] ?? "") : ""
    readonly property string routeContext: networkState.available ? JSON.stringify([
        networkState.routeKey ?? "", [...networkState.adapters, ...networkState.wired].map(device =>
            [device.interface, device.connected, device.uuid, device.details]),
        networkState.profiles.filter(p => p.active).map(profile => [profile.uuid, profile.state]),
        networkState.warp.running, networkState.warp.connected, networkState.warp.mode]) : ""
    escapeHandler: informationPopup ? (() => informationPopup.close())
        : ports.popupOpen ? (() => ports.closePopup()) : null
    onRouteContextChanged: {
        publicIp.context = routeContext;
        if (informationPopup && active) Qt.callLater(publicIp.lookup);
    }
    headerActions: RowLayout {
        spacing: 4
        ShellSwitch {
            objectName: "wifiToggle"
            text: checked ? qsTr("Turn Wi-Fi off") : qsTr("Turn Wi-Fi on")
            checked: root.networkState.wifiEnabled
            enabled: root.canAct && root.networkState.hardwareEnabled && root.networkState.adapters.length > 0
            onToggled: {
                const requested = checked;
                checked = Qt.binding(() => root.networkState.wifiEnabled);
                root.service.run("radio", {enabled: requested});
            }
        }
        NetworkIconButton {
            id: information
            objectName: "wifiInfo"; iconName: "info"; text: qsTr("Wi-Fi information")
            enabled: root.active; checked: networkInfo.visible
            onClicked: { if (networkInfo.visible) networkInfo.close(); else networkInfo.open(); }
            InfoPopover {
                id: networkInfo
                objectName: "wifiInfoPopup"; button: information; active: root.active
                onAboutToShow: {
                    root.informationPopup = networkInfo;
                    ports.closePopup(); warpMenu.close(); root.publicIp.lookup();
                }
                onDismissed: if (root.informationPopup === networkInfo) root.informationPopup = null
                ShellText { text: root.accessStatus; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted }
                InfoRow { objectName: "wifiNetworkInfo"; label: qsTr("Network"); value: root.adapter?.connection ?? "" }
                InfoRow { objectName: "wifiInterfaceInfo"; label: qsTr("Interface"); value: root.adapter?.interface ?? "" }
                InfoRow { objectName: "wifiLocalIpInfo"; label: qsTr("Local IP"); value: root.localAddress }
                InfoRow { objectName: "wifiPublicIpInfo"; label: qsTr("Public IP"); value: root.publicIp.label; copyText: root.publicIp.address }
                InfoRow { objectName: "wifiMacInfo"; label: qsTr("MAC address"); value: root.adapter?.mac ?? "" }
                InfoRow { objectName: "wifiGatewayInfo"; label: qsTr("Gateway"); value: root.ipDetail("IPv4 gateway") || root.ipDetail("IPv6 gateway"); visible: value !== "" }
                InfoRow { objectName: "wifiDnsInfo"; label: qsTr("DNS"); value: [root.ipDetail("IPv4 DNS"), root.ipDetail("IPv6 DNS")].filter(Boolean).join("\n"); visible: value !== "" }
                InfoRow { objectName: "wifiIpv6Info"; label: qsTr("IPv6"); value: root.ipDetail("IPv6"); visible: value !== "" }
            }
        }
        NetworkIconButton {
            objectName: "wifiScan"; iconName: "refresh-cw"; text: qsTr("Scan for Wi-Fi networks")
            enabled: root.canAct && root.networkState.wifiEnabled && !!root.adapter
            onClicked: root.service.scan()
        }
        NetworkIconButton {
            objectName: "networkEdit"; iconName: "pencil"
            text: qsTr("Manage network connections")
            onClicked: root.editor()
        }
    }
    readonly property var passwordField: {
        if (!selected) return null;
        for (let i = 0; i < networkRepeater.count; i++) {
            const entry = networkRepeater.itemAt(i);
            if (entry?.record.key === selected.key) return entry.passwordField;
        }
        return null;
    }
    readonly property var networkState: service.state
    readonly property var adapter: networkState.adapters.find(a => a.interface === service.interfaceName) ?? null
    readonly property var networks: networkState.wifiEnabled ? networkState.networks.filter(n => n.interface === service.interfaceName) : []
    readonly property bool available: networkState.available && service.loaded
    readonly property bool canAct: root.active && available && !service.busy
    readonly property var statsDevice: adapter?.connected ? adapter : networkState.wired.find(d => d.connected) ?? null
    readonly property var rates: service.traffic?.[statsDevice?.interface] ?? null
    readonly property var securityNames: ({"open": qsTr("Open"), "owe": qsTr("Enhanced Open"),
        "wpa-psk": qsTr("WPA/WPA2 Personal"), "sae": qsTr("WPA3 Personal"),
        "enterprise": qsTr("Enterprise"), "wep": qsTr("WEP")})
    readonly property string accessStatus: !service.loaded ? qsTr("Loading network status…") : !available ? qsTr("Network service unavailable")
        : (({full: qsTr("Internet access"), portal: qsTr("Network sign-in required"), limited: qsTr("Limited internet access"),
            none: qsTr("No internet connection"), unknown: qsTr("Internet access not checked")})[networkState.connectivity] ?? networkState.connectivity)

    ListModel { id: networkModel; dynamicRoles: true }
    ListModel { id: vpnModel; dynamicRoles: true }
    ListModel { id: wiredModel; dynamicRoles: true }
    ListModel { id: adapterModel; dynamicRoles: true }
    function syncModels(): void {
        if (!networkModel) return;
        Models.sync(networkModel, networks, "key", true);
        Models.sync(vpnModel, networkState.profiles.filter(p => ["vpn", "wireguard"].includes(p.kind)), "uuid", false);
        Models.sync(wiredModel, networkState.wired.filter(d => d.carrier), "interface", false);
        Models.sync(adapterModel, networkState.adapters, "interface", false);
        if (selected) {
            selected = networks.find(n => n.key === selected.key) ?? selected;
            if (selected.connected) { passwordText = ""; selected = null; }
        }
    }
    onNetworkStateChanged: syncModels()
    onNetworksChanged: syncModels()
    onActiveChanged: {
        service.observing = active;
        if (!active) speedTest.cancel();
    }
    Component.onCompleted: { syncModels(); service.observing = active; publicIp.context = routeContext; }
    Component.onDestruction: { service.observing = false; speedTest.cancel(); }

    function choose(network): void {
        if (selected?.key !== network.key) {
            passwordText = "";
            showPassword = false;
            passwordRequired = !network.uuid && ["wpa-psk", "sae"].includes(network.security);
        }
        selected = network;
        if (!passwordRequired) return;
        Qt.callLater(() => {
            const field = root.passwordField;
            if (!field?.visible) return;
            field.forceActiveFocus();
            const view = networkScroll.contentItem;
            const bottom = field.mapToItem(networkScroll.contentChildren[0], 0, field.height).y + 8;
            if (view && bottom > view.contentY + view.height)
                view.contentY = Math.max(0, Math.min(bottom - view.height, view.contentHeight - view.height));
        });
    }
    function join(): void {
        if (!selected) return;
        service.run("connect", {interface: selected.interface, uuid: selected.uuid,
            ssid: selected.ssid, ap: selected.ap, security: selected.security,
            password: passwordText, autoconnect: true}, selected.key);
    }
    function editor(uuid = ""): void {
        Quickshell.execDetached(uuid ? ["nm-connection-editor", "--edit", uuid]
            : ["nm-connection-editor"]);
        closeRequested();
    }
    readonly property var warpModes: [
        {value: "warp+doh", label: qsTr("WARP + DNS over HTTPS")},
        {value: "warp+dot", label: qsTr("WARP + DNS over TLS")},
        {value: "warp", label: qsTr("WARP")},
        {value: "doh", label: qsTr("DNS over HTTPS only")},
        {value: "dot", label: qsTr("DNS over TLS only")},
        {value: "tunnel_only", label: qsTr("Tunnel only")},
        {value: "proxy", label: qsTr("Local proxy")}
    ]
    readonly property string activeWarpMode: networkState.warp.running && warpModes.some(m => m.value === networkState.warp.mode)
        ? networkState.warp.mode : service.warpMode
    function ipDetail(label: string): string {
        const prefix = label + ": ";
        return (adapter?.details ?? "").split("\n").find(line => line.startsWith(prefix))?.slice(prefix.length) ?? "";
    }
    function networkHint(network): string {
        return network.ssid + "\n" + network.strength + qsTr("% signal") + " · " + securityNames[network.security]
            + "\n" + network.frequency + " MHz · " + network.bssid + "\n" + network.interface
            + (network.uuid ? qsTr(" · Saved") : "")
            + (network.connected ? "\n" + qsTr("Click to disconnect") : "\n" + qsTr("Click to connect"));
    }
    function networkAction(network): void {
        if (network.connected) service.run("disconnect", {uuid: adapter.uuid}, network.key);
        else if (!network.uuid && ["enterprise", "wep"].includes(network.security)) editor();
        else {
            choose(network);
            if (network.uuid || ["open", "owe"].includes(network.security) || passwordText.length) join();
            else Qt.callLater(() => root.passwordField?.forceActiveFocus());
        }
    }
    function warpAction(): void {
        service.run("warp", {action: networkState.warp.running ? "disconnect" : "connect",
            mode: activeWarpMode, register: service.warpRegisterNext}, "warp");
    }
    function rateText(value): string {
        if (typeof value !== "number") return "—";
        return value < 1024 ? Math.round(value) + " B/s" : value < 1048576 ? (value / 1024).toFixed(1) + " KiB/s" : (value / 1048576).toFixed(1) + " MiB/s";
    }
    Connections {
        target: root.service
        function onInterfaceNameChanged(): void { root.informationPopup?.close(); }
        function onCompleted(operation, success): void {
            if (operation !== "connect" || root.service.pendingKey !== root.selected?.key) return;
            if (success) { root.passwordText = ""; root.selected = null; }
            else if (root.selected && ["wpa-psk", "sae"].includes(root.selected.security)) {
                root.passwordRequired = true;
                root.choose(root.selected);
            }
        }
    }
    component WarpModeItem: NetworkMenuItem {
        required property string mode
        objectName: "warpMode:" + mode
        text: root.warpModes.find(m => m.value === mode)?.label ?? mode
        checkable: true
        autoExclusive: true
        checked: root.activeWarpMode === mode
        enabled: root.canAct
        onTriggered: root.service.selectWarpMode(mode)
    }
    component Note: ShellText {
        Layout.fillWidth: true
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        RowLayout {
            visible: root.service.error !== ""
            Layout.fillWidth: true
            Note { objectName: "networkError"; text: root.service.error; color: Theme.danger }
            NetworkIconButton {
                iconName: "x"; text: qsTr("Dismiss network error")
                onClicked: { if (root.service.dismissError) root.service.dismissError(); else root.service.error = ""; }
            }
        }
        RowLayout {
            visible: root.service.busy || !root.service.loaded
            BusySpinner { objectName: "networkActivity"; implicitWidth: 16; implicitHeight: 16 }
            Note { text: !root.service.loaded ? qsTr("Loading…") : root.service.pending === "disconnect" ? qsTr("Disconnecting…") : qsTr("Applying network change…") }
        }
        DrawerColumn {
            id: networkScroll
            objectName: "networkScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            NetworkSection {
                objectName: "wirelessSection"
                title: qsTr("Wireless"); flat: true; collapsible: false
                NetworkChoice {
                    objectName: "wifiAdapter"; Layout.fillWidth: true
                    visible: root.networkState.adapters.length > 1
                    model: adapterModel; textRole: "identity"
                    currentIndex: root.networkState.adapters.findIndex(a => a.interface === root.service.interfaceName)
                    onActivated: { root.service.interfaceName = adapterModel.get(currentIndex).identity; root.selected = null; root.syncModels(); }
                }
                NetworkButton {
                    visible: root.networkState.connectivity === "portal"
                    text: qsTr("Open network sign-in")
                    onClicked: { Qt.openUrlExternally("http://neverssl.com"); root.closeRequested(); }
                }
                Note {
                    visible: !networkModel.count
                    text: !root.networkState.adapters.length ? qsTr("No Wi-Fi adapter found.")
                        : !root.networkState.hardwareEnabled ? qsTr("Wi-Fi is blocked by hardware or airplane mode.")
                        : !root.networkState.wifiEnabled ? qsTr("Wi-Fi is off.") : qsTr("No networks found. Scan again or open Manage networks.")
                }
                Repeater {
                    id: networkRepeater
                    model: networkModel
                    delegate: ColumnLayout {
                        id: networkEntry
                        required property var record
                        readonly property alias passwordField: password
                        readonly property bool selected: root.selected?.key === record.key
                        Layout.fillWidth: true
                        spacing: 4
                        NetworkRow {
                            objectName: "wifiNetwork:" + networkEntry.record.key
                            text: networkEntry.record.ssid
                            wireless: true
                            strength: networkEntry.record.strength
                            secured: !["open", "owe"].includes(networkEntry.record.security)
                            connected: networkEntry.record.connected
                            hint: root.networkHint(networkEntry.record)
                            enabled: root.canAct && root.networkState.wifiEnabled
                            onClicked: root.networkAction(networkEntry.record)
                        }
                        RowLayout {
                            objectName: networkEntry.selected ? "wifiAuthentication" : ""
                            visible: networkEntry.selected && root.passwordRequired && !networkEntry.record.connected
                            Layout.fillWidth: true
                            Layout.leftMargin: 64
                            NetworkField {
                                id: password
                                objectName: networkEntry.selected ? "wifiPassword" : ""
                                Layout.fillWidth: true
                                placeholderText: qsTr("Network password")
                                Accessible.name: qsTr("Password for %1").arg(networkEntry.record.ssid)
                                text: networkEntry.selected ? root.passwordText : ""
                                onTextEdited: root.passwordText = text
                                enabled: root.canAct
                                echoMode: root.showPassword ? TextInput.Normal : TextInput.Password
                                onAccepted: if (root.canAct && text.length) root.join()
                            }
                            NetworkIconButton {
                                iconName: root.showPassword ? "eye-off" : "eye"
                                text: root.showPassword ? qsTr("Hide password") : qsTr("Show password")
                                onClicked: root.showPassword = !root.showPassword
                            }
                            NetworkIconButton {
                                objectName: networkEntry.selected ? "wifiSubmit" : ""
                                iconName: "arrow-right"; text: qsTr("Connect to %1").arg(networkEntry.record.ssid)
                                enabled: root.canAct && root.passwordText.length > 0
                                onClicked: root.join()
                            }
                            NetworkIconButton {
                                iconName: "x"; text: qsTr("Cancel connection")
                                onClicked: { root.selected = null; root.passwordText = ""; }
                            }
                        }
                    }
                }
            }
            NetworkSection {
                objectName: "ethernetSection"; visible: wiredModel.count > 0
                title: qsTr("Ethernet"); flat: true; collapsible: false
                Repeater {
                    model: wiredModel
                    delegate: NetworkRow {
                        required property var record
                        text: record.connection || record.interface
                        iconName: "network"
                        connected: record.connected
                        hint: record.interface + "\n" + record.state + " · " + record.speed + " Mb/s\n" + record.details
                        enabled: root.canAct
                        onClicked: root.service.run(record.connected ? "disconnect" : "connect", record.connected ? {uuid: record.uuid} : {interface: record.interface})
                    }
                }
            }
            NetworkSection {
                objectName: "vpnSection"
                title: qsTr("VPN"); flat: true; collapsible: false
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    NetworkRow {
                        objectName: "warpToggle"
                        text: qsTr("Cloudflare"); iconName: "cloudflare"
                        connected: root.networkState.warp.connected
                        hint: root.networkState.warp.state + "\n" + (root.warpModes.find(m => m.value === root.activeWarpMode)?.label ?? "")
                            + "\n" + (root.networkState.warp.running ? qsTr("Click to disconnect and stop WARP") : qsTr("Click to connect WARP"))
                        enabled: root.canAct && root.networkState.warp.available
                        onClicked: root.warpAction()
                    }
                    NetworkIconButton {
                        id: warpSettings
                        readonly property alias menu: warpMenu
                        objectName: "warpSettings"; iconName: "settings"; text: qsTr("Cloudflare settings")
                        enabled: root.canAct && root.networkState.warp.available
                        onClicked: warpMenu.open()
                        Menu {
                            id: warpMenu
                            onAboutToShow: { root.informationPopup?.close(); ports.closePopup(); }
                            objectName: "warpMenu"
                            popupType: Popup.Item
                            x: warpSettings.width - width; y: warpSettings.height
                            width: 280
                            padding: 6
                            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                            background: Surface { color: Theme.background; radius: Theme.controlRadius }
                            // Fixed children keep order during asynchronous drawer incubation.
                            // Registering a device is independent of the mutually exclusive modes.
                            WarpModeItem { mode: "warp+doh" }
                            WarpModeItem { mode: "warp+dot" }
                            WarpModeItem { mode: "warp" }
                            WarpModeItem { mode: "doh" }
                            WarpModeItem { mode: "dot" }
                            WarpModeItem { mode: "tunnel_only" }
                            WarpModeItem { mode: "proxy" }
                            MenuSeparator {
                                objectName: "warpModeSeparator"
                                padding: 6
                                contentItem: Rectangle { implicitHeight: 1; color: Theme.border }
                            }
                            NetworkMenuItem {
                                id: warpRegistration
                                objectName: "warpRegistration"
                                text: qsTr("Register on new connect")
                                checkable: true
                                checked: root.service.warpRegisterNext
                                onTriggered: root.service.setWarpRegistration(!root.service.warpRegisterNext)
                                PassiveToolTip {
                                    target: warpRegistration
                                    text: qsTr("Create a registration on the next connection. This may replace an existing registration. Connecting accepts Cloudflare's terms.")
                                }
                            }
                        }
                    }
                }
                Repeater {
                    model: vpnModel
                    delegate: NetworkRow {
                        required property var record
                        objectName: "networkProfile:" + record.uuid
                        text: record.name; iconName: "shield-lock"
                        connected: record.state === "activated"
                        hint: record.state + " · " + record.kind + "\n" + (record.active ? qsTr("Click to disconnect") : qsTr("Click to connect"))
                        enabled: root.canAct
                        onClicked: root.service.run(record.active ? "disconnect" : "connect", {uuid: record.uuid}, record.uuid)
                    }
                }
            }
            PortsControls {
                id: ports
                objectName: "portsSection"; Layout.fillWidth: true
                Layout.leftMargin: 4; Layout.rightMargin: 4
                service: root.portsService; active: root.active
                interfaceName: root.adapter?.connected ? root.adapter.interface
                    : root.networkState.wired.find(device => device.connected)?.interface ?? ""
                connected: interfaceName !== ""
                onPopupOpened: { warpMenu.close(); root.informationPopup?.close(); }
            }
        }
        Button {
            id: stats
            objectName: "networkStats"
            visible: root.statsDevice !== null
            Layout.fillWidth: true
            implicitHeight: 26
            padding: 4
            hoverEnabled: true
            focusPolicy: Qt.NoFocus
            text: qsTr("Transfer rates for %1. Link speed is the negotiated adapter rate, not an internet speed test.").arg(root.statsDevice?.interface ?? "")
            contentItem: RowLayout {
                spacing: 6
                Icon { name: "arrow-down"; Layout.preferredWidth: 14; Layout.preferredHeight: 14; color: Theme.muted }
                Note { objectName: "downloadRate"; text: root.rateText(root.rates?.down); Layout.fillWidth: false; font.family: Theme.monospaceFamily }
                Icon { name: "arrow-up"; Layout.preferredWidth: 14; Layout.preferredHeight: 14; color: Theme.muted }
                Note { text: root.rateText(root.rates?.up); Layout.fillWidth: false; font.family: Theme.monospaceFamily }
                Item { Layout.fillWidth: true }
                Note { visible: !!root.statsDevice?.speed; text: (root.statsDevice?.speed ?? 0) + " Mb/s"; Layout.fillWidth: false }
            }
            background: Item {}
            PassiveToolTip { target: stats }
        }
        Button {
            id: speedButton
            objectName: "speedTestButton"
            Layout.fillWidth: true
            implicitHeight: speedDetails.visible ? 64 : 48
            padding: 10
            hoverEnabled: true
            enabled: root.speedTest.running || (root.canAct && root.networkState.connectivity !== "none")
            opacity: enabled ? 1 : 0.5
            text: root.speedTest.running ? qsTr("Cancel speed test")
                : root.speedTest.result ? qsTr("Run speed test again") : qsTr("Test internet speed")
            Accessible.name: text
            onClicked: if (root.speedTest.running) root.speedTest.cancel(); else root.speedTest.start()
            // Explicit geometry avoids feedback between nested layout size hints
            // while the asynchronous page is being created or the label changes.
            contentItem: Item {
                Item {
                    id: speedGroup
                    anchors.centerIn: parent
                    width: Math.min(parent.width, 34 + speedLabels.naturalWidth + (speedCancel.visible ? 28 : 0))
                    height: parent.height
                    Item {
                        id: speedGlyph
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: 22; height: 22
                        Icon {
                            anchors.fill: parent
                            visible: !root.speedTest.running
                            name: "gauge"
                            color: speedButton.hovered || speedButton.visualFocus ? Theme.accent : Theme.text
                        }
                        BusySpinner { anchors.fill: parent; visible: root.speedTest.running }
                    }
                    Item {
                        id: speedLabels
                        readonly property real naturalWidth: Math.max(speedTitle.implicitWidth,
                            speedDetails.visible ? speedDetails.implicitWidth : 0)
                        anchors.left: speedGlyph.right
                        anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.max(0, speedGroup.width - 34 - (speedCancel.visible ? 28 : 0))
                        height: speedTitle.implicitHeight + (speedDetails.visible ? 4 + speedDetails.implicitHeight : 0)
                        ShellText {
                            id: speedTitle
                            objectName: "speedTestLabel"
                            anchors.top: parent.top
                            width: parent.width
                            text: root.speedTest.running ? qsTr("Testing internet speed…") : qsTr("Internet speed test")
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            font.weight: Font.Medium
                            elide: Text.ElideRight
                            color: Theme.text
                        }
                        ShellText {
                            id: speedDetails
                            objectName: "speedTestResult"
                            anchors.top: speedTitle.bottom
                            anchors.topMargin: 4
                            width: parent.width
                            visible: !root.speedTest.running && (!!root.speedTest.result || root.speedTest.error !== "")
                            text: root.speedTest.error || (root.speedTest.result ? qsTr("↓ %1 Mb/s   ↑ %2 Mb/s · %3 ms")
                                .arg(root.speedTest.result.download.toFixed(1)).arg(root.speedTest.result.upload.toFixed(1))
                                .arg(root.speedTest.result.ping.toFixed(0)) : "")
                            color: root.speedTest.error ? Theme.danger : Theme.muted
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            font.pixelSize: Theme.smallFontSize
                            elide: Text.ElideRight
                        }
                    }
                    Icon {
                        id: speedCancel
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        visible: root.speedTest.running
                        name: "x"
                        width: 16; height: 16
                        color: Theme.muted
                    }
                }
            }
            background: ButtonBackground {
                idleColor: Theme.surface
                highlighted: speedButton.hovered || speedButton.visualFocus
                pressed: speedButton.down
            }
            PassiveToolTip {
                target: speedButton
                text: speedButton.text + "\n" + (root.speedTest.result ? qsTr("Server: %1\nLatency: %2 ms · Jitter: %3 ms\nMeasured %4")
                    .arg(root.speedTest.result.server).arg(root.speedTest.result.ping.toFixed(1))
                    .arg(root.speedTest.result.jitter.toFixed(1)).arg(root.speedTest.result.timestamp)
                    : root.speedTest.error || qsTr("Measures the current internet route, including any VPN. Downloads and uploads test data."))
            }
        }
    }
}
