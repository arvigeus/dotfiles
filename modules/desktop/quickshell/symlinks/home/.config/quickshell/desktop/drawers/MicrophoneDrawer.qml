import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Show the selected input device, its gain and mute state, with a live level meter while the drawer is open. List other available inputs and supported device profiles, and make switching between built-in, headset and external microphones direct."),
                qsTr("Show applications or streams currently capturing audio when that information is available, together with any supported per-application input controls. Distinguish a muted microphone from an unavailable device or an application that is not recording."),
                qsTr("Keep the bar indicator synchronized with the actual capture and mute state. Closing the drawer should stop its level-meter updates, while an application's ongoing recording remains under that application's control.")
            ].join("\n\n")
        }
    }
}
