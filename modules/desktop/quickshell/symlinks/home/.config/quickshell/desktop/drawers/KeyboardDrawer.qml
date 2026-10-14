import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Show the active input language and the available layout or input-method choices, starting with the existing EN/BG and EN/VI pairs. Make the selected pair and the currently active language easy to tell apart, and let either be changed directly."),
                qsTr("Keep the drawer and bar synchronized with keyboard shortcuts and changes made outside the shell. Retain the selected pair and active language across shell restarts, login and reboot. If the Vietnamese input method is unavailable, explain that state and keep the working language choices usable."),
                qsTr("Display a Telex shortcut reference for Vietnamese input, covering tone marks, modified letters and how to undo a transformation. Keep it easy to consult while learning or checking a shortcut."),
                qsTr("Plan to add keyboard backlight controls: on/off, brightness and supported lighting modes. Show the current setting, keep it synchronized with hardware keys and explain when the device does not support backlight control."),
                qsTr("Possible additions include key-repeat delay and speed, Caps Lock behavior or remapping, Caps Lock and Num Lock indicators, and a reference for keyboard shortcuts. Keep language selection prominent as these controls are added.")
            ].join("\n\n")
        }
    }
}
