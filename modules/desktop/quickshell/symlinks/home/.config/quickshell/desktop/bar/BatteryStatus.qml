import QtQuick
import Quickshell.Services.UPower
import "../ui"

QtObject {
    property var device: UPower.displayDevice
    readonly property bool available: !!device && device.isPresent && device.type === UPowerDeviceType.Battery
    readonly property bool charging: available && device.state === UPowerDeviceState.Charging
    readonly property real percentage: available ? device.percentage * 100 : -1
    readonly property string label: available && isFinite(percentage) ? Math.round(percentage) + "%" : ""
    readonly property string iconName: charging ? "battery-charging" : available && percentage <= 20 ? "battery-low" : available && percentage >= 80 ? "battery-full" : "battery-medium"
    readonly property color iconColor: available && percentage <= 15 && !charging ? Theme.warning : available ? Theme.text : Theme.muted
    readonly property string description: available ? qsTr("Battery · %1 · %2").arg(label).arg(UPowerDeviceState.toString(device.state)) : qsTr("No system battery")
}
