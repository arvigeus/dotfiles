pragma ComponentBehavior: Bound
import QtQuick
import QtQml.Models
import Quickshell.Networking
import "../ui/NetworkIcons.js" as NetworkIcons

// Native change notifications keep the bar live even while the drawer is closed.
// Only the drawer requests scans; the bar does not start a scanner or helper.
QtObject {
    id: root
    property var provider: Networking
    readonly property bool enabled: provider.wifiEnabled && provider.wifiHardwareEnabled
    readonly property var devices: provider.devices.values.filter(d => d.type === DeviceType.Wifi)
    readonly property var network: {
        let found = null;
        for (const device of root.devices)
            for (const candidate of device.networks.values)
                if (candidate.connected && (!found || candidate.signalStrength > found.signalStrength)) found = candidate;
        return found;
    }
    readonly property int strength: Math.round((network?.signalStrength ?? 0) * 100)
    readonly property string iconName: NetworkIcons.wifi(strength, enabled, network !== null)
    readonly property string description: !enabled ? qsTr("Wi-Fi is off")
        : network ? network.name + " · " + strength + qsTr("% signal") : qsTr("Wi-Fi · Not connected")
    readonly property Instantiator observers: Instantiator {
        model: root.devices
        delegate: QtObject {
            required property var modelData
            Component.onCompleted: modelData.scannerEnabled = false
        }
    }
}
