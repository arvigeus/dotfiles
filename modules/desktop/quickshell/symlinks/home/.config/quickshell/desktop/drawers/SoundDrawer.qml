import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Show the default playback device with its volume and mute state, then the other available outputs. Make switching between speakers, headphones, Bluetooth audio and display audio straightforward, with useful names and supported device profiles."),
                qsTr("Include per-application playback volume and output routing where available, keeping active streams easy to identify. Show the configured volume limit clearly, and keep mute distinct from a quiet volume setting."),
                qsTr("React cleanly when an output is disconnected or becomes unavailable. Microphone selection and capture controls belong in the separate Microphone drawer; this drawer is for sound going out."),
                qsTr("Sound boost option.")
            ].join("\n\n")
        }
    }
}
