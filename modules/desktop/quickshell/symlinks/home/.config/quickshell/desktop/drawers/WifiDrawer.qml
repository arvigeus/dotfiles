pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Networking
import "../ui"
import "../ui/NetworkIcons.js" as NetworkIcons
import "network"

// Wi-Fi, Ethernet, radio and saved-network actions use Quickshell.Networking.
// NetworkService covers VPN profiles, WARP, IP details and new Wi-Fi profiles.
DrawerPage {
    id: root
    property var networking: Networking
    property var service: NetworkService
    property var speedTest: SpeedTestService
    property var portsService: PortsService
    property var publicIp: PublicIpService
    property var deviceDiscovery: DeviceDiscoveryService
    property string trafficRoot: "/sys/class/net"
    property var selected: null
    property string passwordText: ""
    property bool showPassword: false
    property bool passwordRequired: false
    property string connectionError: ""
    property var scanningDevice: null
    property var trafficSample: null
    property var rates: null
    property Popup informationPopup: null
    property var vpnImportMenu: null

    readonly property var networkState: service.state
    readonly property bool available: networking.backend === NetworkBackendType.NetworkManager
    readonly property bool canAct: active && available && !service.busy
    readonly property var wifiDevices: networking.devices.values.filter(d => d.type === DeviceType.Wifi)
    readonly property var wiredDevices: networking.devices.values.filter(d => d.type === DeviceType.Wired)
    readonly property var adapter: wifiDevices.find(d => d.name === service.interfaceName) ?? wifiDevices[0] ?? null
    readonly property bool wifiOn: networking.wifiEnabled && networking.wifiHardwareEnabled
    readonly property var connectedNetwork: adapter?.networks.values.find(n => n.connected) ?? null
    // Out-of-range saved networks have no signal; sort by icon level so small
    // signal changes do not reorder rows.
    readonly property var networks: !wifiOn || !adapter ? [] : adapter.networks.values.filter(n => n.connected || n.signalStrength > 0).sort((a, b) => Number(b.connected) - Number(a.connected) || Number(b.known) - Number(a.known) || NetworkIcons.level(b.signalStrength * 100) - NetworkIcons.level(a.signalStrength * 100) || a.name.localeCompare(b.name))
    readonly property var details: networkState.details?.[adapter?.name ?? ""] ?? null
    readonly property string localAddress: (details?.ipv4?.[0] ?? "").split("/")[0]
    readonly property var statsDevice: adapter?.connected ? adapter : wiredDevices.find(d => d.connected) ?? null
    readonly property string statsInterface: active ? statsDevice?.name ?? "" : ""
    readonly property string discoveryContext: JSON.stringify([statsInterface, networkState.details?.[statsInterface]?.ipv4 ?? []])
    onDiscoveryContextChanged: deviceDiscovery.clear()
    readonly property string routeContext: service.loaded ? JSON.stringify([networkState.active, networkState.warp.connected ? networkState.warp.mode : ""]) : ""
    readonly property string errorText: service.error || connectionError
    readonly property var securityNames: ({
            "open": qsTr("Open"),
            "owe": qsTr("Enhanced Open"),
            "wpa-psk": qsTr("WPA/WPA2 Personal"),
            "sae": qsTr("WPA3 Personal"),
            "enterprise": qsTr("Enterprise"),
            "wep": qsTr("WEP"),
            "unknown": qsTr("Unknown security")
        })
    readonly property string accessStatus: !available ? qsTr("Network service unavailable") : (({
                [NetworkConnectivity.Full]: qsTr("Internet access"),
                [NetworkConnectivity.Portal]: qsTr("Network sign-in required"),
                [NetworkConnectivity.Limited]: qsTr("Limited internet access"),
                [NetworkConnectivity.None]: qsTr("No internet connection")
            })[networking.connectivity] ?? qsTr("Internet access not checked"))
    readonly property var passwordField: {
        if (!selected)
            return null;
        for (let i = 0; i < networkRepeater.count; i++) {
            const entry = networkRepeater.itemAt(i);
            if (entry?.network === selected)
                return entry.passwordField;
        }
        return null;
    }
    escapeHandler: informationPopup ? (() => informationPopup.close()) : vpnImportMenu ? (() => vpnImportMenu.close()) : ports.popupOpen ? (() => ports.closePopup()) : null
    onRouteContextChanged: {
        deviceDiscovery.clear();
        publicIp.context = routeContext;
        if (informationPopup && active)
            Qt.callLater(publicIp.lookup);
    }
    // The native scanner rescans about every ten seconds while enabled.
    readonly property var scanTarget: active ? adapter : null
    onScanTargetChanged: updateScanner()
    function updateScanner(): void {
        if (scanningDevice && scanningDevice !== scanTarget)
            scanningDevice.scannerEnabled = false;
        scanningDevice = scanTarget;
        if (scanTarget)
            scanTarget.scannerEnabled = true;
    }
    onActiveChanged: {
        service.observing = active;
        if (!active) {
            speedTest.cancel();
            deviceDiscovery.cancel();
            vpnImportMenu?.close();
        }
    }
    Component.onCompleted: {
        service.observing = active;
        publicIp.context = routeContext;
        updateScanner();
    }
    Component.onDestruction: {
        service.observing = false;
        speedTest.cancel();
        deviceDiscovery.cancel();
        if (scanningDevice)
            scanningDevice.scannerEnabled = false;
    }

    headerActions: RowLayout {
        spacing: 4
        ShellSwitch {
            objectName: "wifiToggle"
            text: checked ? qsTr("Turn Wi-Fi off") : qsTr("Turn Wi-Fi on")
            checked: root.networking.wifiEnabled
            enabled: root.active && root.networking.wifiHardwareEnabled && root.wifiDevices.length > 0
            onToggled: {
                const requested = checked;
                checked = Qt.binding(() => root.networking.wifiEnabled);
                root.networking.wifiEnabled = requested;
            }
        }
        IconButton {
            id: information
            objectName: "wifiInfo"
            iconName: "info"
            text: qsTr("Wi-Fi information")
            enabled: root.active
            checked: networkInfo.visible
            onClicked: {
                if (networkInfo.visible)
                    networkInfo.close();
                else
                    networkInfo.open();
            }
            InfoPopover {
                id: networkInfo
                objectName: "wifiInfoPopup"
                button: information
                active: root.active
                onAboutToShow: {
                    root.informationPopup = networkInfo;
                    ports.closePopup();
                    warpMenu.close();
                    root.vpnImportMenu?.close();
                    root.publicIp.lookup();
                }
                onDismissed: if (root.informationPopup === networkInfo)
                    root.informationPopup = null
                ShellText {
                    text: root.accessStatus
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: Theme.muted
                }
                InfoRow {
                    objectName: "wifiNetworkInfo"
                    label: qsTr("Network")
                    value: root.connectedNetwork?.name ?? ""
                }
                InfoRow {
                    objectName: "wifiInterfaceInfo"
                    label: qsTr("Interface")
                    value: root.adapter?.name ?? ""
                }
                InfoRow {
                    objectName: "wifiLocalIpInfo"
                    label: qsTr("Local IP")
                    value: root.localAddress
                }
                InfoRow {
                    objectName: "wifiPublicIpInfo"
                    label: qsTr("Public IP")
                    value: root.publicIp.label
                    copyText: root.publicIp.address
                }
                InfoRow {
                    objectName: "wifiMacInfo"
                    label: qsTr("MAC address")
                    value: root.adapter?.address ?? ""
                }
                InfoRow {
                    objectName: "wifiGatewayInfo"
                    label: qsTr("Gateway")
                    value: root.details?.ipv4Gateway || root.details?.ipv6Gateway || ""
                    visible: value !== ""
                }
                InfoRow {
                    objectName: "wifiDnsInfo"
                    label: qsTr("DNS")
                    value: [...(root.details?.ipv4Dns ?? []), ...(root.details?.ipv6Dns ?? [])].join("\n")
                    visible: value !== ""
                }
                InfoRow {
                    objectName: "wifiIpv6Info"
                    label: qsTr("IPv6")
                    value: (root.details?.ipv6 ?? []).join(", ")
                    visible: value !== ""
                }
            }
        }
        IconButton {
            objectName: "networkEdit"
            iconName: "pencil"
            text: qsTr("Manage network connections")
            onClicked: root.editor()
        }
    }

    function securityKind(network): string {
        switch (network?.security) {
        case WifiSecurityType.Open:
            return "open";
        case WifiSecurityType.Owe:
            return "owe";
        case WifiSecurityType.WpaPsk:
        case WifiSecurityType.Wpa2Psk:
            return "wpa-psk";
        case WifiSecurityType.Sae:
            return "sae";
        case WifiSecurityType.StaticWep:
        case WifiSecurityType.DynamicWep:
            return "wep";
        case WifiSecurityType.Unknown:
            return "unknown";
        default:
            return "enterprise";
        }
    }
    function needsPassword(network): bool {
        return ["wpa-psk", "sae"].includes(securityKind(network));
    }
    function clearSelection(): void {
        selected = null;
        passwordText = "";
        passwordRequired = false;
    }
    function choose(network): void {
        if (selected !== network) {
            passwordText = "";
            showPassword = false;
            passwordRequired = !network.known && needsPassword(network);
        }
        selected = network;
        if (!passwordRequired)
            return;
        Qt.callLater(() => {
            const field = root.passwordField;
            if (!field?.visible)
                return;
            field.forceActiveFocus();
            const view = networkScroll.contentItem;
            const bottom = field.mapToItem(networkScroll.contentChildren[0], 0, field.height).y + 8;
            if (view && bottom > view.contentY + view.height)
                view.contentY = Math.max(0, Math.min(bottom - view.height, view.contentHeight - view.height));
        });
    }
    // Saved networks connect natively. New ones get a user-scoped profile from
    // the helper, which native activation cannot create.
    function join(): void {
        const network = selected;
        if (!network)
            return;
        service.dismissError();
        connectionError = "";
        if (network.known) {
            if (passwordText.length)
                network.connectWithPsk(passwordText);
            else
                network.connect();
        } else {
            service.run("join", {
                interface: network.device?.name ?? adapter?.name ?? "",
                ssid: network.name,
                security: securityKind(network),
                password: passwordText
            }, network.name);
        }
    }
    function editor(uuid = ""): void {
        Apps.launch(uuid ? ["nm-connection-editor", "--edit", uuid] : ["nm-connection-editor"]);
        closeRequested();
    }
    function networkHint(network): string {
        return network.name + "\n" + Math.round(network.signalStrength * 100) + qsTr("% signal") + " · " + securityNames[securityKind(network)] + "\n" + (network.device?.name ?? "") + (network.known ? qsTr(" · Saved") : "") + "\n" + (network.connected || network.state === ConnectionState.Connecting ? qsTr("Click to disconnect") : qsTr("Click to connect"));
    }
    function networkAction(network): void {
        connectionError = "";
        if (network.connected || network.state === ConnectionState.Connecting)
            network.disconnect();
        else if (!network.known && ["enterprise", "wep", "unknown"].includes(securityKind(network)))
            editor();
        else {
            choose(network);
            if (network.known || !needsPassword(network) || passwordText.length)
                join();
            else
                Qt.callLater(() => root.passwordField?.forceActiveFocus());
        }
    }
    function connectionFailed(network, reason): void {
        connectionError = reason === ConnectionFailReason.NoSecrets ? qsTr("%1 needs a password.").arg(network.name) : reason === ConnectionFailReason.WifiNetworkLost ? qsTr("%1 is out of range.").arg(network.name) : qsTr("Could not connect to %1. Check the password and signal.").arg(network.name);
        if (!needsPassword(network))
            return;
        choose(network);
        passwordRequired = true;
        choose(network);
    }
    function warpAction(): void {
        service.run("warp", {
            action: networkState.warp.running ? "disconnect" : "connect",
            mode: activeWarpMode
        }, "warp");
    }
    function rateText(value): string {
        if (typeof value !== "number")
            return "—";
        return value < 1024 ? Math.round(value) + " B/s" : value < 1048576 ? (value / 1024).toFixed(1) + " KiB/s" : (value / 1048576).toFixed(1) + " MiB/s";
    }
    // Interface byte counters; local reads only, never test traffic.
    function sampleTraffic(): void {
        rxBytes.reload();
        txBytes.reload();
        const received = Number(rxBytes.text()), sent = Number(txBytes.text()), time = Date.now();
        if (!rxBytes.text() || !Number.isFinite(received) || !Number.isFinite(sent)) {
            trafficSample = null;
            rates = null;
            return;
        }
        const old = trafficSample;
        trafficSample = {
            received,
            sent,
            time
        };
        const seconds = old ? (time - old.time) / 1000 : 0;
        if (seconds > 0 && received >= old.received && sent >= old.sent)
            rates = {
                down: (received - old.received) / seconds,
                up: (sent - old.sent) / seconds
            };
    }
    onStatsInterfaceChanged: {
        trafficSample = null;
        rates = null;
    }
    FileView {
        id: rxBytes
        path: root.statsInterface ? root.trafficRoot + "/" + root.statsInterface + "/statistics/rx_bytes" : ""
        blockLoading: true
        printErrors: false
    }
    FileView {
        id: txBytes
        path: root.statsInterface ? root.trafficRoot + "/" + root.statsInterface + "/statistics/tx_bytes" : ""
        blockLoading: true
        printErrors: false
    }
    Timer {
        interval: 2000
        repeat: true
        triggeredOnStart: true
        running: root.statsInterface !== ""
        onTriggered: root.sampleTraffic()
    }

    readonly property var warpModes: [
        {
            value: "warp+doh",
            label: qsTr("WARP + DNS over HTTPS")
        },
        {
            value: "warp+dot",
            label: qsTr("WARP + DNS over TLS")
        },
        {
            value: "warp",
            label: qsTr("WARP")
        },
        {
            value: "doh",
            label: qsTr("DNS over HTTPS only")
        },
        {
            value: "dot",
            label: qsTr("DNS over TLS only")
        },
        {
            value: "tunnel_only",
            label: qsTr("Tunnel only")
        },
        {
            value: "proxy",
            label: qsTr("Local proxy")
        }
    ]
    readonly property string activeWarpMode: networkState.warp.running && warpModes.some(m => m.value === networkState.warp.mode) ? networkState.warp.mode : service.warpMode
    Connections {
        target: root.service
        function onInterfaceNameChanged(): void {
            root.informationPopup?.close();
        }
        function onCompleted(operation, success): void {
            if (operation !== "join" || root.service.pendingKey !== root.selected?.name)
                return;
            if (success)
                root.clearSelection();
            else if (root.needsPassword(root.selected)) {
                root.passwordRequired = true;
                root.choose(root.selected);
            }
        }
    }
    component WarpModeItem: ShellMenuItem {
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
            visible: root.errorText !== ""
            Layout.fillWidth: true
            Note {
                objectName: "networkError"
                text: root.errorText
                color: Theme.danger
            }
            IconButton {
                iconName: "x"
                text: qsTr("Dismiss network error")
                onClicked: {
                    root.service.dismissError();
                    root.connectionError = "";
                }
            }
        }
        RowLayout {
            visible: root.service.busy
            BusySpinner {
                objectName: "networkActivity"
                implicitWidth: 16
                implicitHeight: 16
            }
            Note {
                text: root.service.pending === "disconnect" ? qsTr("Disconnecting…") : qsTr("Applying network change…")
            }
        }
        DrawerColumn {
            id: networkScroll
            objectName: "networkScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            NetworkSection {
                objectName: "wirelessSection"
                title: qsTr("Wireless")
                flat: true
                collapsible: false
                ShellChoice {
                    objectName: "wifiAdapter"
                    Layout.fillWidth: true
                    visible: root.wifiDevices.length > 1
                    model: root.wifiDevices.map(d => d.name)
                    currentIndex: root.wifiDevices.indexOf(root.adapter)
                    onActivated: index => {
                        root.service.interfaceName = root.wifiDevices[index].name;
                        root.clearSelection();
                    }
                }
                ShellButton {
                    visible: root.networking.connectivity === NetworkConnectivity.Portal
                    text: qsTr("Open network sign-in")
                    onClicked: {
                        Qt.openUrlExternally("http://neverssl.com");
                        root.closeRequested();
                    }
                }
                Note {
                    visible: !root.networks.length
                    text: !root.wifiDevices.length ? qsTr("No Wi-Fi adapter found.") : !root.networking.wifiHardwareEnabled ? qsTr("Wi-Fi is blocked by hardware or airplane mode.") : !root.networking.wifiEnabled ? qsTr("Wi-Fi is off.") : qsTr("Searching for networks…")
                }
                Repeater {
                    id: networkRepeater
                    model: ScriptModel {
                        values: root.networks
                    }
                    delegate: ColumnLayout {
                        id: networkEntry
                        required property var modelData
                        readonly property var network: modelData
                        readonly property alias passwordField: password
                        readonly property bool selected: root.selected === network
                        Layout.fillWidth: true
                        spacing: 4
                        Connections {
                            target: networkEntry.network
                            function onConnectionFailed(reason): void {
                                root.connectionFailed(networkEntry.network, reason);
                            }
                            function onConnectedChanged(): void {
                                if (networkEntry.network.connected && networkEntry.selected)
                                    root.clearSelection();
                            }
                        }
                        NetworkRow {
                            objectName: "wifiNetwork:" + networkEntry.network.name
                            text: networkEntry.network.name
                            wireless: true
                            strength: Math.round(networkEntry.network.signalStrength * 100)
                            secured: !["open", "owe"].includes(root.securityKind(networkEntry.network))
                            connected: networkEntry.network.connected
                            hint: root.networkHint(networkEntry.network)
                            enabled: root.canAct
                            onClicked: root.networkAction(networkEntry.network)
                        }
                        RowLayout {
                            objectName: networkEntry.selected ? "wifiAuthentication" : ""
                            visible: networkEntry.selected && root.passwordRequired && !networkEntry.network.connected
                            Layout.fillWidth: true
                            Layout.leftMargin: 64
                            InputField {
                                id: password
                                objectName: networkEntry.selected ? "wifiPassword" : ""
                                Layout.fillWidth: true
                                placeholderText: qsTr("Network password")
                                Accessible.name: qsTr("Password for %1").arg(networkEntry.network.name)
                                text: networkEntry.selected ? root.passwordText : ""
                                onTextEdited: root.passwordText = text
                                enabled: root.canAct
                                echoMode: root.showPassword ? TextInput.Normal : TextInput.Password
                                onAccepted: if (root.canAct && text.length)
                                    root.join()
                            }
                            IconButton {
                                iconName: root.showPassword ? "eye-off" : "eye"
                                text: root.showPassword ? qsTr("Hide password") : qsTr("Show password")
                                onClicked: root.showPassword = !root.showPassword
                            }
                            IconButton {
                                objectName: networkEntry.selected ? "wifiSubmit" : ""
                                iconName: "arrow-right"
                                text: qsTr("Connect to %1").arg(networkEntry.network.name)
                                enabled: root.canAct && root.passwordText.length > 0
                                onClicked: root.join()
                            }
                            IconButton {
                                iconName: "x"
                                text: qsTr("Cancel connection")
                                onClicked: root.clearSelection()
                            }
                        }
                    }
                }
            }
            NetworkSection {
                objectName: "ethernetSection"
                visible: wiredRepeater.count > 0
                title: qsTr("Ethernet")
                flat: true
                collapsible: false
                Repeater {
                    id: wiredRepeater
                    model: ScriptModel {
                        values: root.wiredDevices.filter(d => d.hasLink)
                    }
                    delegate: NetworkRow {
                        required property var modelData
                        objectName: "wiredDevice:" + modelData.name
                        text: root.networkState.details?.[modelData.name]?.connection || modelData.name
                        iconName: "network"
                        connected: modelData.connected
                        hint: modelData.name + "\n" + ConnectionState.toString(modelData.state) + (modelData.linkSpeed ? " · " + modelData.linkSpeed + " Mb/s" : "") + "\n" + (modelData.connected ? qsTr("Click to disconnect") : qsTr("Click to connect"))
                        enabled: root.canAct && !!modelData.network
                        onClicked: if (modelData.connected)
                            modelData.network.disconnect()
                        else
                            modelData.network.connect()
                    }
                }
            }
            NetworkSection {
                objectName: "vpnSection"
                title: qsTr("VPN")
                flat: true
                collapsible: false
                action: IconButton {
                    id: vpnAdd
                    objectName: "vpnAdd"
                    iconName: "plus"
                    text: qsTr("Add VPN connection")
                    readonly property alias menu: vpnMenu
                    enabled: root.active && root.available
                    checked: vpnMenu.visible
                    onClicked: if (vpnMenu.visible)
                        vpnMenu.close()
                    else
                        vpnMenu.open()
                    Menu {
                        id: vpnMenu
                        objectName: "vpnImportMenu"
                        popupType: Popup.Item
                        x: vpnAdd.width - width
                        y: vpnAdd.height
                        width: 220
                        padding: 6
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                        background: Surface {
                            color: Theme.background
                            radius: Theme.controlRadius
                        }
                        onAboutToShow: {
                            root.vpnImportMenu = vpnMenu;
                            root.informationPopup?.close();
                            ports.closePopup();
                            warpMenu.close();
                        }
                        onClosed: if (root.vpnImportMenu === vpnMenu)
                            root.vpnImportMenu = null
                        ShellMenuItem {
                            objectName: "importWireguard"
                            text: qsTr("Import WireGuard…")
                            onTriggered: {
                                root.service.chooseWireguardConfig();
                                root.closeRequested();
                            }
                        }
                    }
                }
                Item {
                    id: warpRow
                    objectName: "warpRow"
                    readonly property alias background: warpBackground
                    Layout.fillWidth: true
                    Layout.leftMargin: 28
                    implicitHeight: Math.max(warpToggle.implicitHeight, warpSettings.implicitHeight)
                    ButtonBackground {
                        id: warpBackground
                        anchors.fill: parent
                        idleColor: warpToggle.connected ? Theme.accentSurface : "transparent"
                        highlighted: warpToggle.highlighted
                        pressed: warpToggle.down || warpSettings.down
                    }
                    RowLayout {
                        anchors.fill: parent
                        spacing: 0
                        NetworkRow {
                            id: warpToggle
                            objectName: "warpToggle"
                            Layout.leftMargin: 0
                            highlighted: hovered || visualFocus || warpSettings.hovered || warpSettings.visualFocus || warpMenu.visible
                            background: Item {}
                            text: qsTr("Cloudflare")
                            iconName: "cloudflare"
                            connected: root.networkState.warp.connected
                            hint: root.networkState.warp.state + "\n" + (root.warpModes.find(m => m.value === root.activeWarpMode)?.label ?? "") + "\n" + (root.networkState.warp.running ? qsTr("Click to disconnect and stop WARP") : qsTr("Click to connect WARP. Registers automatically if needed and accepts Cloudflare's terms."))
                            enabled: root.canAct && root.networkState.warp.available
                            onClicked: root.warpAction()
                        }
                        IconButton {
                            id: warpSettings
                            readonly property alias menu: warpMenu
                            objectName: "warpSettings"
                            iconName: "settings"
                            text: qsTr("Cloudflare settings")
                            iconColor: warpToggle.foreground
                            background: Item {}
                            enabled: root.canAct && root.networkState.warp.available
                            onClicked: warpMenu.open()
                            Menu {
                                id: warpMenu
                                onAboutToShow: {
                                    root.informationPopup?.close();
                                    ports.closePopup();
                                    root.vpnImportMenu?.close();
                                }
                                objectName: "warpMenu"
                                popupType: Popup.Item
                                x: warpSettings.width - width
                                y: warpSettings.height
                                width: 280
                                padding: 6
                                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                                background: Surface {
                                    color: Theme.background
                                    radius: Theme.controlRadius
                                }
                                // Fixed children keep order during asynchronous drawer incubation.
                                WarpModeItem {
                                    mode: "warp+doh"
                                }
                                WarpModeItem {
                                    mode: "warp+dot"
                                }
                                WarpModeItem {
                                    mode: "warp"
                                }
                                WarpModeItem {
                                    mode: "doh"
                                }
                                WarpModeItem {
                                    mode: "dot"
                                }
                                WarpModeItem {
                                    mode: "tunnel_only"
                                }
                                WarpModeItem {
                                    mode: "proxy"
                                }
                            }
                        }
                    }
                }
                Repeater {
                    model: KeyedModel {
                        values: root.networkState.profiles
                        keyField: "uuid"
                    }
                    delegate: NetworkRow {
                        required property var modelData
                        objectName: "networkProfile:" + modelData.uuid
                        text: modelData.name
                        iconName: "shield-lock"
                        connected: modelData.state === "activated"
                        hint: modelData.state + " · " + modelData.kind + "\n" + (modelData.active ? qsTr("Click to disconnect") : qsTr("Click to connect"))
                        enabled: root.canAct
                        onClicked: root.service.run(modelData.active ? "disconnect" : "connect", {
                            uuid: modelData.uuid
                        }, modelData.uuid)
                    }
                }
            }
            DevicesControls {
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                service: root.deviceDiscovery
                active: root.active
                interfaceName: root.statsDevice?.name ?? ""
                localAddresses: (root.networkState.details?.[interfaceName]?.ipv4 ?? []).map(address => address.split("/")[0])
                gatewayAddress: root.networkState.details?.[interfaceName]?.ipv4Gateway ?? ""
            }
            PortsControls {
                id: ports
                objectName: "portsSection"
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                service: root.portsService
                active: root.active
                interfaceName: root.statsDevice?.name ?? ""
                connected: interfaceName !== ""
                onPopupOpened: {
                    warpMenu.close();
                    root.informationPopup?.close();
                    root.vpnImportMenu?.close();
                }
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
            readonly property int linkSpeed: root.statsDevice?.linkSpeed ?? 0
            text: qsTr("Transfer rates for %1. Link speed is the negotiated adapter rate, not an internet speed test.").arg(root.statsDevice?.name ?? "")
            contentItem: RowLayout {
                spacing: 6
                Icon {
                    name: "arrow-down"
                    Layout.preferredWidth: 14
                    Layout.preferredHeight: 14
                    color: Theme.muted
                }
                Note {
                    objectName: "downloadRate"
                    text: root.rateText(root.rates?.down)
                    Layout.fillWidth: false
                    font.family: Theme.monospaceFamily
                }
                Icon {
                    name: "arrow-up"
                    Layout.preferredWidth: 14
                    Layout.preferredHeight: 14
                    color: Theme.muted
                }
                Note {
                    text: root.rateText(root.rates?.up)
                    Layout.fillWidth: false
                    font.family: Theme.monospaceFamily
                }
                Item {
                    Layout.fillWidth: true
                }
                Note {
                    visible: stats.linkSpeed > 0
                    text: stats.linkSpeed + " Mb/s"
                    Layout.fillWidth: false
                }
            }
            background: Item {}
            PassiveToolTip {
                target: stats
            }
        }
        Button {
            id: speedButton
            objectName: "speedTestButton"
            Layout.fillWidth: true
            implicitHeight: speedDetails.visible ? 64 : 48
            padding: 10
            hoverEnabled: true
            enabled: root.speedTest.running || (root.canAct && root.networking.connectivity !== NetworkConnectivity.None)
            opacity: enabled ? 1 : 0.5
            text: root.speedTest.running ? qsTr("Cancel speed test") : root.speedTest.result ? qsTr("Run speed test again") : qsTr("Test internet speed")
            Accessible.name: text
            onClicked: if (root.speedTest.running)
                root.speedTest.cancel()
            else
                root.speedTest.start()
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
                        width: 22
                        height: 22
                        Icon {
                            anchors.fill: parent
                            visible: !root.speedTest.running
                            name: "gauge"
                            color: speedButton.hovered || speedButton.visualFocus ? Theme.accent : Theme.text
                        }
                        BusySpinner {
                            anchors.fill: parent
                            visible: root.speedTest.running
                        }
                    }
                    Item {
                        id: speedLabels
                        readonly property real naturalWidth: Math.max(speedTitle.implicitWidth, speedDetails.visible ? speedDetails.implicitWidth : 0)
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
                            text: root.speedTest.error || (root.speedTest.result ? qsTr("↓ %1 Mb/s   ↑ %2 Mb/s · %3 ms").arg(root.speedTest.result.download.toFixed(1)).arg(root.speedTest.result.upload.toFixed(1)).arg(root.speedTest.result.ping.toFixed(0)) : "")
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
                        width: 16
                        height: 16
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
                text: speedButton.text + "\n" + (root.speedTest.result ? qsTr("Server: %1\nLatency: %2 ms · Jitter: %3 ms\nMeasured %4").arg(root.speedTest.result.server).arg(root.speedTest.result.ping.toFixed(1)).arg(root.speedTest.result.jitter.toFixed(1)).arg(root.speedTest.result.timestamp) : root.speedTest.error || qsTr("Measures the current internet route, including any VPN. Downloads and uploads test data."))
            }
        }
    }
}
