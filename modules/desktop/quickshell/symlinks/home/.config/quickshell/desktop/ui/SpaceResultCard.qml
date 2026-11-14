pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../spaces/movies" as Media

Button {
    id: root
    required property var result
    property bool selectedRow: false
    property var output: QsWindow.window?.screen ?? null
    property string error: ""
    readonly property var entity: result.payload?.title || result.payload?.item || ({})
    readonly property string artworkSource: [result.artwork, entity.poster, typeof entity.cover === "string" ? entity.cover : entity.cover?.url, entity.thumbnail, entity.image, entity.logo, entity.favicon].find(value => typeof value === "string" && /^(https?:\/\/|file:\/\/|\/)/.test(value)) || ""
    readonly property bool portrait: ["movie", "series", "episode", "game"].includes(result.kind)
    signal opened
    implicitHeight: result.reason ? 112 : 84
    Accessible.description: [result.subtitle, result.availability, result.reason].filter(Boolean).join(" · ")
    padding: Theme.spacingMedium
    text: result.title || ""
    hoverEnabled: true
    PassiveToolTip {
        target: root
        text: [root.result.reason, root.result.availability].filter(Boolean).join(" · ")
    }
    function openResult(play) {
        error = "";
        if (SpaceState.open(result.space, output, Object.assign({}, result.payload, {
            play: !!play
        })))
            opened();
        else
            error = qsTr("This Space is unavailable.");
    }
    onClicked: openResult(false)
    background: ButtonBackground {
        highlighted: root.selectedRow || root.hovered || root.visualFocus
        pressed: root.down
        idleColor: Theme.surface
    }
    contentItem: RowLayout {
        spacing: Theme.gap
        Rectangle {
            Layout.preferredWidth: root.portrait ? 48 : root.result.kind === "youtube" ? 80 : 56
            Layout.preferredHeight: root.portrait ? 64 : root.result.kind === "youtube" ? 48 : 56
            radius: Theme.controlRadius
            color: Theme.surface
            clip: true
            Icon {
                anchors.centerIn: parent
                width: 24
                height: 24
                name: root.result.icon || "search"
                color: Theme.muted
                visible: artwork.loadStatus !== Image.Ready
            }
            Media.CachedImage {
                id: artwork
                objectName: "spaceResultArtwork"
                anchors.fill: parent
                remoteSource: root.visible ? root.artworkSource : ""
                sourceSize.width: parent.width * 2
                sourceSize.height: parent.height * 2
                fillMode: Image.PreserveAspectCrop
                visible: loadStatus === Image.Ready
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            ShellText {
                Layout.fillWidth: true
                text: root.text
                elide: Text.ElideRight
            }
            ShellText {
                Layout.fillWidth: true
                text: root.error || root.result.subtitle || ""
                font.pixelSize: Theme.smallFontSize
                color: root.error ? Theme.danger : Theme.muted
                elide: Text.ElideRight
            }
            ShellText {
                Layout.fillWidth: true
                visible: !!root.result.reason
                text: root.result.reason || ""
                font.pixelSize: Theme.smallFontSize
                color: Theme.text
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }
        IconButton {
            objectName: "playSpaceResult"
            visible: !!root.result.playable
            iconName: "play"
            text: qsTr("Play %1").arg(root.text)
            onClicked: root.openResult(true)
        }
    }
}
