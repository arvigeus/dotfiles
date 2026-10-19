import QtQuick
import "../ui"

// Add a DrawerPage file and one catalogue entry. Bar callers use its stable key.
// Only Spaces has a drawer shortcut; all drawers share Theme.drawerWidth.
DrawerHost {
    definitions: [
        DrawerDefinition {
            key: "spaces"
            title: qsTr("Spaces")
            source: Qt.resolvedUrl("SpacesDrawer.qml")
            edge: DrawerDefinition.Left
            shortcut: "spaces"
        },
        DrawerDefinition {
            key: "tray"
            title: qsTr("System tray")
            source: Qt.resolvedUrl("TrayDrawer.qml")
        },
        DrawerDefinition {
            key: "clipboard"
            title: qsTr("Clipboard")
            source: Qt.resolvedUrl("ClipboardDrawer.qml")
        },
        DrawerDefinition {
            key: "screenshot"
            title: qsTr("Screenshot")
            source: Qt.resolvedUrl("ScreenshotDrawer.qml")
        },
        DrawerDefinition {
            key: "recording"
            title: qsTr("Screen recording")
            source: Qt.resolvedUrl("RecordingDrawer.qml")
        },
        DrawerDefinition {
            key: "wifi"
            title: qsTr("Wi-Fi")
            source: Qt.resolvedUrl("WifiDrawer.qml")
        },
        DrawerDefinition {
            key: "bluetooth"
            title: qsTr("Bluetooth")
            source: Qt.resolvedUrl("BluetoothDrawer.qml")
        },
        DrawerDefinition {
            key: "sound"
            title: qsTr("Sound")
            source: Qt.resolvedUrl("SoundDrawer.qml")
        },
        DrawerDefinition {
            key: "microphone"
            title: qsTr("Microphone")
            source: Qt.resolvedUrl("MicrophoneDrawer.qml")
        },
        DrawerDefinition {
            key: "keyboard"
            title: qsTr("Keyboard")
            source: Qt.resolvedUrl("KeyboardDrawer.qml")
        },
        DrawerDefinition {
            key: "displays"
            title: qsTr("Displays")
            source: Qt.resolvedUrl("DisplaysDrawer.qml")
        },
        DrawerDefinition {
            key: "disks"
            title: qsTr("Disks")
            source: Qt.resolvedUrl("DisksDrawer.qml")
        },
        DrawerDefinition {
            key: "battery"
            title: qsTr("Battery")
            source: Qt.resolvedUrl("BatteryDrawer.qml")
        },
        DrawerDefinition {
            key: "performance"
            title: qsTr("Performance")
            source: Qt.resolvedUrl("PerformanceDrawer.qml")
            shortcut: "performance"
        },
        DrawerDefinition {
            key: "weather"
            title: qsTr("Time and weather")
            source: Qt.resolvedUrl("WeatherDrawer.qml")
        },
        DrawerDefinition {
            key: "notifications"
            title: qsTr("Events and notifications")
            source: Qt.resolvedUrl("NotificationsDrawer.qml")
        }
    ]
}
