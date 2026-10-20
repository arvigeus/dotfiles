import QtQuick
import Quickshell
import Quickshell.Services.UPower
import "../ui"
import "../drawers/displays"
import "../drawers/keyboard"
import "../drawers/weather"
import "../drawers/capture"
import "../drawers/power/Format.js" as PowerFormat

Item {
    id: root
    property real maximumWidth: implicitWidth
    property string outputName: ""
    property var displayComfort: ComfortService
    property var inputLanguage: InputLanguage
    property date localDate: new Date()
    readonly property string powerProfile: PowerProfiles.profile === PowerProfile.PowerSaver ? "power-saver"
        : PowerProfiles.profile === PowerProfile.Performance ? "performance" : "balanced"
    signal drawerRequested(string key)
    readonly property alias trayIsland: tray
    readonly property alias toolsIsland: tools
    readonly property alias systemIsland: system
    readonly property alias notificationsIsland: notifications

    implicitWidth: islands.implicitWidth
    implicitHeight: Theme.controlHeight
    width: Math.min(implicitWidth, Math.max(0, maximumWidth))
    height: implicitHeight
    clip: true

    // Feature pages stay lazy; live status does not depend on an open drawer.
    NetworkStatus { id: networkStatus }
    BluetoothStatus { id: bluetoothStatus }
    AudioStatus { id: audioStatus }
    MicrophoneStatus { id: microphoneStatus }
    BatteryStatus { id: batteryStatus }
    WeatherStatus { id: weatherStatus; objectName: "islandWeatherStatus" }
    SystemClock { id: clock; precision: SystemClock.Minutes; onDateChanged: root.localDate = date }
    Connections {
        target: LocationSettings
        function onChanged(): void { root.localDate = new Date(); }
    }

    Flickable {
        id: viewport
        objectName: "statusViewport"
        anchors.fill: parent
        contentWidth: islands.implicitWidth
        contentHeight: height
        flickableDirection: Flickable.HorizontalFlick
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentWidth > width
        onWidthChanged: contentX = Math.max(0, Math.min(contentX, contentWidth - width))
        onContentWidthChanged: contentX = Math.max(0, Math.min(contentX, contentWidth - width))

        WheelScroll {
            view: viewport
            orientation: Qt.Horizontal
            verticalToHorizontal: true
            scrollGestureEnabled: true
        }

        Row {
            id: islands
            spacing: Theme.spacingMedium
            BarIsland {
                id: tray
                objectName: "trayIsland"
                entries: [
                    BarEntry { key: "tray"; title: qsTr("System tray"); iconName: "chevron-up" }
                ]
                onDrawerRequested: key => root.drawerRequested(key)
            }
            BarIsland {
                id: tools
                objectName: "toolsIsland"
                entries: [
                    BarEntry { key: "clipboard"; title: qsTr("Clipboard"); iconName: "clipboard" },
                    BarEntry {
                        key: "capture"; title: qsTr("Capture")
                        iconName: CaptureService.sessionActive ? "video" : "camera"
                        iconColor: CaptureService.sessionActive ? Theme.danger : CaptureService.waiting ? Theme.accent : Theme.text
                        label: CaptureService.sessionActive ? CaptureService.recordingTime : CaptureService.waiting ? String(CaptureService.remaining) : ""
                        description: CaptureService.sessionActive ? (CaptureService.paused ? qsTr("Recording paused · %1") : qsTr("Recording · %1 · open to stop")).arg(CaptureService.recordingTime)
                            : CaptureService.waiting ? qsTr("Screenshot in %1 s · open to cancel").arg(CaptureService.remaining)
                            : qsTr("Capture · screenshots, recording and webcam")
                    }
                ]
                onDrawerRequested: key => root.drawerRequested(key)
            }
            BarIsland {
                id: system
                objectName: "systemIsland"
                entries: [
                    BarEntry { key: "wifi"; title: qsTr("Wi-Fi"); iconName: networkStatus.iconName; description: networkStatus.description },
                    BarEntry { key: "bluetooth"; title: qsTr("Bluetooth"); iconName: bluetoothStatus.iconName; iconColor: bluetoothStatus.iconColor; description: bluetoothStatus.description },
                    BarEntry { key: "sound"; title: qsTr("Sound"); iconName: audioStatus.iconName; iconColor: audioStatus.iconColor; description: audioStatus.description },
                    BarEntry { key: "microphone"; title: qsTr("Microphone"); iconName: microphoneStatus.iconName; iconColor: microphoneStatus.iconColor; description: microphoneStatus.description },
                    BarEntry { key: "keyboard"; title: qsTr("Keyboard"); iconName: "keyboard"; label: root.inputLanguage.label; description: root.inputLanguage.description },
                    BarEntry {
                        key: "displays"; title: qsTr("Displays"); iconName: "monitor"
                        iconColor: root.displayComfort.awakeFor(root.outputName) ? Theme.accent : Theme.text
                        description: root.displayComfort.awakeFor(root.outputName) ? qsTr("Displays · Keep awake") : qsTr("Displays")
                    },
                    BarEntry { key: "disks"; title: qsTr("Disks"); iconName: "hard-drive" },
                    BarEntry { key: "battery"; title: qsTr("Battery"); iconName: batteryStatus.iconName; label: batteryStatus.label; iconColor: batteryStatus.iconColor; description: batteryStatus.description },
                    BarEntry {
                        key: "performance"; title: qsTr("Performance"); iconName: PowerFormat.profileIcon(root.powerProfile)
                        description: qsTr("Performance · %1").arg(PowerFormat.profile(root.powerProfile))
                    }
                ]
                onDrawerRequested: key => root.drawerRequested(key)
            }
            BarIsland {
                id: notifications
                objectName: "notificationsIsland"
                entries: [
                    BarEntry {
                        key: "weather"; title: qsTr("Time and weather"); iconName: weatherStatus.iconName
                        label: Qt.formatTime(root.localDate, "HH:mm")
                        description: Qt.formatDateTime(root.localDate, "dddd, d MMMM yyyy · HH:mm t") + "\n" + weatherStatus.description
                    },
                    BarEntry {
                        key: "notifications"; title: qsTr("Events and notifications"); iconName: "calendar-days"
                        label: Qt.formatDate(root.localDate, "ddd d")
                        secondaryIconName: "bell"; badge: "2"; attention: true
                        description: qsTr("Events and notifications preview")
                    }
                ]
                onDrawerRequested: key => root.drawerRequested(key)
            }
        }
    }
}
