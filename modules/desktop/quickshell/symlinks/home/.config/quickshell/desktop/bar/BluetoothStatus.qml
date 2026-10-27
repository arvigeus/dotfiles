import "../ui"
import QtQuick
import Quickshell.Bluetooth

QtObject {
    readonly property var adapters: Bluetooth.adapters.values
    readonly property var connected: Bluetooth.devices.values.filter(device => {
        return device.connected;
    })
    readonly property bool enabled: adapters.some(adapter => {
        return adapter.enabled;
    })
    readonly property string iconName: enabled ? "bluetooth" : "bluetooth-off"
    readonly property color iconColor: enabled ? Theme.text : Theme.muted
    readonly property string description: !adapters.length ? qsTr("Bluetooth · No adapter") : !enabled ? qsTr("Bluetooth · Off") : connected.length ? qsTr("Bluetooth · %1").arg(connected.map(device => {
        return device.name;
    }).join(", ")) : qsTr("Bluetooth · On")
}
