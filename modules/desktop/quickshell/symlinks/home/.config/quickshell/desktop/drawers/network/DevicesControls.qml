pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../ui"

NetworkSection {
    id: root
    objectName: "networkDevicesSection"
    property var service: DeviceDiscoveryService
    property string interfaceName: ""
    property bool active: false
    property var localAddresses: []
    property string gatewayAddress: ""
    property bool expandPending: false
    title: qsTr("Devices on this network")
    iconName: "network"
    summary: service.running ? qsTr("Scanning…")
        : service.loaded && service.error === ""
            ? (service.hosts.length === 1 ? qsTr("1 device") : qsTr("%1 devices").arg(service.hosts.length)) : ""
    hint: qsTr("Click to find reachable devices on the connected private network. The list opens when discovery finishes. Sleeping or firewalled devices may not respond.")
    function toggle(): void {
        if (expanded) { expanded = false; return; }
        if (!active || interfaceName === "" || service.running) return;
        expandPending = true;
        service.start(interfaceName);
    }
    function finishExpansion(): void {
        if (!expandPending || service.running || (!service.loaded && service.error === "")) return;
        expandPending = false;
        expanded = active;
    }
    onActiveChanged: if (!active) { expandPending = false; expanded = false; }
    onInterfaceNameChanged: { expandPending = false; expanded = false; }
    Connections {
        target: root.service
        function onRunningChanged(): void { if (!root.service.running) Qt.callLater(root.finishExpansion); }
        function onLoadedChanged(): void {
            if (!root.service.loaded) root.expanded = false;
            else Qt.callLater(root.finishExpansion);
        }
        function onErrorChanged(): void { Qt.callLater(root.finishExpansion); }
    }
    function deviceHint(host): string {
        const lines = [host.address];
        if (localAddresses.includes(host.address)) lines.push(qsTr("This computer"));
        if (host.address === gatewayAddress) lines.push(qsTr("Network gateway"));
        if (typeof host.responseMs === "number")
            lines.push(qsTr("Discovery response time: %1 ms").arg(host.responseMs.toFixed(1)));
        return lines.join("\n");
    }
    ShellText {
        visible: root.service.error !== "" || (root.service.loaded && root.service.hosts.length === 0)
        text: root.service.error || qsTr("No devices responded.")
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
    }
    Repeater {
        model: root.service.hosts
        delegate: ShellText {
            id: addressLabel
            required property var modelData
            objectName: "networkDevice:" + modelData.address
            text: modelData.address
            textFormat: Text.PlainText
            font.family: Theme.monospaceFamily
            Layout.fillWidth: true
            Accessible.description: root.deviceHint(modelData)
            PassiveToolTip { target: addressLabel; text: root.deviceHint(addressLabel.modelData) }
        }
    }
}
