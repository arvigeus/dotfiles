import QtQuick
import Quickshell
import "../ui"
import "../drawers/displays"
import "../drawers/keyboard"
import "../drawers/weather"

Item {
    id: root
    property real maximumWidth: implicitWidth
    property string outputName: ""
    property var displayComfort: ComfortService
    property var inputLanguage: InputLanguage
    property date localDate: new Date()
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
    AudioStatus { id: audioStatus }
    MicrophoneStatus { id: microphoneStatus }
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
                    BarEntry { key: "screenshot"; title: qsTr("Screenshot"); iconName: "camera" },
                    BarEntry { key: "recording"; title: qsTr("Screen recording"); iconName: "video" }
                ]
                onDrawerRequested: key => root.drawerRequested(key)
            }
            BarIsland {
                id: system
                objectName: "systemIsland"
                entries: [
                    BarEntry { key: "wifi"; title: qsTr("Wi-Fi"); iconName: networkStatus.iconName; description: networkStatus.description },
                    BarEntry { key: "bluetooth"; title: qsTr("Bluetooth"); iconName: "bluetooth" },
                    BarEntry { key: "sound"; title: qsTr("Sound"); iconName: audioStatus.iconName; iconColor: audioStatus.iconColor; description: audioStatus.description },
                    BarEntry { key: "microphone"; title: qsTr("Microphone"); iconName: microphoneStatus.iconName; iconColor: microphoneStatus.iconColor; description: microphoneStatus.description },
                    BarEntry { key: "keyboard"; title: qsTr("Keyboard"); iconName: "keyboard"; label: root.inputLanguage.label; description: root.inputLanguage.description },
                    BarEntry {
                        key: "displays"; title: qsTr("Displays"); iconName: "monitor"
                        iconColor: root.displayComfort.awakeFor(root.outputName) ? Theme.accent : Theme.text
                        description: root.displayComfort.awakeFor(root.outputName) ? qsTr("Displays · Keep awake") : qsTr("Displays")
                    },
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
