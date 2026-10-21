import QtQuick
import Quickshell
import Quickshell.Services.UPower
import "../ui"
import "../drawers/displays"
import "../drawers/keyboard"
import "../drawers/weather"
import "../drawers/capture"
import "../drawers/notifications"
import "../drawers/tray"
import "../drawers/power/Format.js" as PowerFormat

Item {
    id: root
    property real maximumWidth: implicitWidth
    property string outputName: ""
    property var displayComfort: ComfortService
    property var inputLanguage: InputLanguage
    property var notificationCenter: NotificationCenter
    property var trayStatus: TrayService
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
                    BarEntry {
                        key: "tray"; title: qsTr("System tray"); iconName: "chevron-up"
                        badge: root.trayStatus.count > 99 ? "99+" : root.trayStatus.count ? String(root.trayStatus.count) : ""
                        badgeReserveText: "99+"
                        attention: root.trayStatus.attention
                        iconColor: attention ? Theme.accent : Theme.text
                        description: (root.trayStatus.count === 1 ? qsTr("1 tray app") : qsTr("%1 tray apps").arg(root.trayStatus.count))
                            + (attention ? "\n" + qsTr("Needs attention: %1").arg(root.trayStatus.attentionItems
                                .map(item => item.title || item.id || qsTr("Unknown application")).join(", ")) : "")
                    }
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
                    BarEntry { key: "keyboard"; title: qsTr("Keyboard"); iconName: "keyboard"; badge: root.inputLanguage.label; badgeReserveText: "BG"; description: root.inputLanguage.description },
                    BarEntry {
                        key: "displays"; title: qsTr("Displays"); iconName: "monitor"
                        iconColor: root.displayComfort.awakeFor(root.outputName) ? Theme.accent : Theme.text
                        description: root.displayComfort.awakeFor(root.outputName) ? qsTr("Displays · Keep awake") : qsTr("Displays")
                    },
                    BarEntry { key: "disks"; title: qsTr("Disks"); iconName: "hard-drive" },
                    BarEntry { key: "battery"; title: qsTr("Battery"); iconName: batteryStatus.iconName; badge: batteryStatus.label; badgeReserveText: "100%"; iconColor: batteryStatus.iconColor; description: batteryStatus.description },
                    BarEntry {
                        key: "performance"; title: qsTr("Performance"); iconName: PowerFormat.profileIcon(root.powerProfile)
                        description: qsTr("Performance · %1").arg(PowerFormat.profile(root.powerProfile))
                    },
                    BarEntry { key: "system"; title: qsTr("System"); iconName: "settings"; description: qsTr("System · updates, boot times and services") }
                ]
                onDrawerRequested: key => root.drawerRequested(key)
            }
            BarIsland {
                id: notifications
                objectName: "notificationsIsland"
                entries: [
                    BarEntry {
                        key: "weather"; title: qsTr("Time and weather"); iconName: weatherStatus.iconName
                        badge: weatherStatus.temperature; badgeReserveText: "−99°"
                        label: Qt.formatTime(root.localDate, "HH:mm")
                        description: Qt.formatDateTime(root.localDate, "dddd, d MMMM yyyy · HH:mm t") + "\n" + weatherStatus.description
                    },
                    BarEntry {
                        key: "events"; title: qsTr("Events and tasks"); iconName: "calendar-days"
                        label: Qt.formatDate(root.localDate, "ddd d")
                        description: qsTr("Calendar, agenda and tasks")
                    },
                    BarEntry {
                        key: "notifications"; title: qsTr("Notifications"); iconName: "bell"
                        badge: root.notificationCenter.unseenCount > 99 ? "99+" : root.notificationCenter.unseenCount ? String(root.notificationCenter.unseenCount) : ""
                        badgeReserveText: "99+"
                        attention: root.notificationCenter.unseenCount > 0
                        iconColor: attention ? Theme.accent : root.notificationCenter.state.paused ? Theme.muted : Theme.text
                        description: (root.notificationCenter.unseenCount === 1 ? qsTr("1 unseen notification") : qsTr("%1 unseen notifications").arg(root.notificationCenter.unseenCount))
                            + (root.notificationCenter.state.paused ? " · " + qsTr("Do Not Disturb") : "")
                    }
                ]
                onDrawerRequested: key => root.drawerRequested(key)
            }
        }
    }
}
