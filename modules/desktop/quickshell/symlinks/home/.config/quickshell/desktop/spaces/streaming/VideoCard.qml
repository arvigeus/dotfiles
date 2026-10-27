import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../movies"

ItemDelegate {
    id: root
    required property var video
    property bool selected: false
    width: 300; height: 250
    padding: 8
    Accessible.name: video.title + ", " + video.creator
    contentItem: ColumnLayout {
        spacing: 8
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: width * 9 / 16
            color: MovieStyle.surface; radius: 8; clip: true
            CachedImage {
                anchors.fill: parent
                remoteSource: root.visible ? root.video.thumbnail || "" : ""
                sourceSize.width: 640; fillMode: Image.PreserveAspectCrop
            }
            Rectangle {
                anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 7
                width: duration.implicitWidth + 12; height: 24; radius: 4; color: "#dd000000"
                MovieText {
                    id: duration; anchors.centerIn: parent; font.pixelSize: 12
                    text: root.video.live ? "LIVE" : root.video.duration > 0 ? Math.floor(root.video.duration / 60) + ":" + String(root.video.duration % 60).padStart(2, "0") : "YouTube"
                }
            }
            Rectangle {
                visible: !!root.video.localPath || ["private", "needs_auth"].includes(root.video.availability)
                anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 7
                width: badge.implicitWidth + 14; height: 24; radius: 4; color: "#dd000000"
                MovieText {
                    id: badge; anchors.centerIn: parent; font.pixelSize: 12
                    text: root.video.localPath ? root.video.audio ? "AUDIO" : "OFFLINE"
                        : "SIGN-IN"
                }
            }
        }
        MovieText {
            Layout.fillWidth: true; Layout.preferredHeight: 42
            text: root.video.title; font.bold: true; wrapMode: Text.Wrap
            maximumLineCount: 2; elide: Text.ElideRight
        }
        MovieText { Layout.fillWidth: true; text: root.video.creator; color: MovieStyle.muted; elide: Text.ElideRight }
        Item { Layout.fillHeight: true }
    }
    background: Rectangle {
        radius: 10
        color: root.selected ? MovieStyle.accentSurface : root.hovered ? "#18ffffff" : "transparent"
        border.color: root.selected || root.visualFocus ? MovieStyle.accent : "transparent"; border.width: 2
    }
}
