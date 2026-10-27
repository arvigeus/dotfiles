pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell.Services.Mpris
import "../../ui"

ColumnLayout {
    id: root
    property bool active: false
    property var players: Mpris.players.values.filter(player => player.dbusName !== "org.mpris.MediaPlayer2.playerctld")
    property bool showHeading: false
    visible: players.length > 0
    spacing: 8

    ShellText {
        visible: root.showHeading
        text: qsTr("Playback")
        font.weight: Font.DemiBold
        Layout.fillWidth: true
    }
    Repeater {
        model: root.players
        delegate: RowLayout {
            id: player
            required property var modelData
            objectName: "audioPlayer:" + modelData.dbusName
            Layout.fillWidth: true
            spacing: 4
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 1
                ShellText {
                    text: player.modelData.trackTitle || player.modelData.identity
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }
                ShellText {
                    text: [player.modelData.trackArtist, player.modelData.identity].filter(s => s).join(" · ")
                    visible: text !== "" && text !== (player.modelData.trackTitle || player.modelData.identity)
                    color: Theme.muted
                    font.pixelSize: Theme.smallFontSize
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }
            }
            IconButton {
                objectName: player.objectName + ":previous"
                iconName: "skip-back"
                text: qsTr("Previous track")
                enabled: root.active && player.modelData.canControl && player.modelData.canGoPrevious
                onClicked: player.modelData.previous()
            }
            IconButton {
                objectName: player.objectName + ":playPause"
                iconName: player.modelData.isPlaying ? "pause" : "play"
                text: player.modelData.isPlaying ? qsTr("Pause") : qsTr("Play")
                enabled: root.active && player.modelData.canControl && player.modelData.canTogglePlaying
                onClicked: player.modelData.togglePlaying()
            }
            IconButton {
                objectName: player.objectName + ":next"
                iconName: "skip-forward"
                text: qsTr("Next track")
                enabled: root.active && player.modelData.canControl && player.modelData.canGoNext
                onClicked: player.modelData.next()
            }
        }
    }
}
