import QtQuick
import Quickshell
import "../ui"

Item {
    id: root
    property real maximumWidth: implicitWidth
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

    // Sample status is confined to these view models. Bind live icons, labels,
    // badges and attention here later; do not instantiate feature pages for it.
    // The clock is real. Weather, language, battery and notification status are mock.
    SystemClock { id: clock; precision: SystemClock.Minutes }

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
                    BarEntry { key: "screenshot"; title: qsTr("Screenshot"); iconName: "camera" },
                    BarEntry { key: "recording"; title: qsTr("Screen recording"); iconName: "video" }
                ]
                onDrawerRequested: key => root.drawerRequested(key)
            }
            BarIsland {
                id: system
                objectName: "systemIsland"
                entries: [
                    BarEntry { key: "wifi"; title: qsTr("Wi-Fi"); iconName: "wifi" },
                    BarEntry { key: "bluetooth"; title: qsTr("Bluetooth"); iconName: "bluetooth" },
                    BarEntry { key: "sound"; title: qsTr("Sound"); iconName: "volume-2" },
                    BarEntry { key: "microphone"; title: qsTr("Microphone"); iconName: "mic" },
                    BarEntry { key: "keyboard"; title: qsTr("Keyboard"); iconName: "keyboard"; label: "EN"; description: qsTr("Active input language preview") },
                    BarEntry { key: "displays"; title: qsTr("Displays"); iconName: "monitor" },
                    BarEntry { key: "disks"; title: qsTr("Disks"); iconName: "hard-drive" },
                    BarEntry { key: "battery"; title: qsTr("Battery"); iconName: "battery-medium"; label: "76%"; description: qsTr("Battery preview") },
                    BarEntry { key: "performance"; title: qsTr("Performance"); iconName: "gauge" },
                    BarEntry { key: "general"; title: qsTr("General"); iconName: "settings" }
                ]
                onDrawerRequested: key => root.drawerRequested(key)
            }
            BarIsland {
                id: notifications
                objectName: "notificationsIsland"
                entries: [
                    BarEntry {
                        key: "weather"; title: qsTr("Clock and weather"); iconName: "cloud-sun"
                        label: Qt.formatTime(clock.date, "HH:mm")
                        description: qsTr("Weather preview")
                    },
                    BarEntry {
                        key: "notifications"; title: qsTr("Events and notifications"); iconName: "calendar-days"
                        label: Qt.formatDate(clock.date, "ddd d")
                        secondaryIconName: "bell"; badge: "2"; attention: true
                        description: qsTr("Events and notifications preview")
                    }
                ]
                onDrawerRequested: key => root.drawerRequested(key)
            }
        }
    }
}
