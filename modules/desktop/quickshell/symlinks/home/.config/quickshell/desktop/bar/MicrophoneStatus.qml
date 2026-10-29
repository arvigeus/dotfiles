import QtQuick
import Quickshell
import Quickshell.Services.Pipewire
import "../ui"
import "../ui/AudioIcons.js" as AudioIcons

Scope {
    readonly property var source: Pipewire.defaultAudioSource
    readonly property bool available: !!source?.audio && source?.properties["device.class"] !== "monitor" && !source.name.endsWith(".monitor")
    PwObjectTracker {
        id: tracker
        objects: [source].filter(node => node)
    }
    readonly property string iconName: !available || source.audio.muted ? "mic-off" : "mic"
    readonly property color iconColor: available ? Theme.text : Theme.muted
    readonly property string description: !available ? qsTr("No microphone available") : qsTr("Microphone: %1%").arg(AudioIcons.level(source.audio)) + (source.audio.muted ? qsTr(" (muted)") : "") + "\n" + (source.nickname || source.description || source.name)
}
