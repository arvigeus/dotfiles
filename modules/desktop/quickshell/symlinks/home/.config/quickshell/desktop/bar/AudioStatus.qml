import QtQuick
import Quickshell
import Quickshell.Services.Pipewire
import "../ui"
import "../ui/AudioIcons.js" as AudioIcons

// Native notifications keep the passive bar current without starting the drawer helper.
Scope {
    readonly property var sink: Pipewire.defaultAudioSink
    PwObjectTracker {
        id: tracker
        objects: [sink].filter(n => n)
    }
    readonly property real volume: AudioIcons.level(sink?.audio)
    readonly property string iconName: AudioIcons.volume(volume, !sink?.audio || sink.audio.muted)
    readonly property color iconColor: volume > 100 ? Theme.accent : Theme.text
    readonly property string outputName: sink?.nickname || sink?.description || sink?.name || qsTr("Default output")
    readonly property string description: !sink?.audio ? qsTr("No audio output") : qsTr("Volume: %1%").arg(volume) + (sink.audio.muted ? qsTr(" (muted)") : "") + "\n" + outputName
}
