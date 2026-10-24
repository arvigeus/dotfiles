import QtQuick
import "../../ui"
import QtQuick.Layouts

MovieButton {
    id: root
    property var cacheService: ImageCache
    function fontSize(value) { return Math.round(value * MovieStyle.fontSize / 14); }
    property url imageSource: ""
    property string fallbackIcon: ""
    property string subtitle: ""
    property string badge: ""
    property bool favorite: false
    property int imageFillMode: Image.PreserveAspectCrop
    padding: 5
    background: Rectangle {
        radius: MovieStyle.controlRadius
        color: root.highlighted || root.hovered ? MovieStyle.accentSurface : "transparent"
        border.width: root.highlighted || root.activeFocus ? 2 : 0
        border.color: MovieStyle.accent
    }
    contentItem: ColumnLayout {
        spacing: 8
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "#80141117"
            radius: MovieStyle.controlRadius
            clip: true
            CrossfadeImage { cacheService: root.cacheService;
                id: artwork
                anchors.fill: parent
                source: root.imageSource
                fillMode: root.imageFillMode
                imageWidth: 400
            }
            Column {
                visible: !artwork.hasImage
                anchors.centerIn: parent
                width: parent.width - 18
                spacing: 10
                MovieIcon { visible: !!root.fallbackIcon; anchors.horizontalCenter: parent.horizontalCenter; name: root.fallbackIcon; width: 30; height: 30; opacity: 0.55 }
                MovieText { width: parent.width; text: root.text; color: MovieStyle.muted; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; maximumLineCount: 4 }
            }
            Rectangle {
                visible: !!root.badge
                anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 8
                width: badgeText.implicitWidth + 16; height: 24
                radius: MovieStyle.controlRadius; color: MovieStyle.background
                MovieText { id: badgeText; anchors.centerIn: parent; text: root.badge; font.family: MovieStyle.fontFamily; font.pixelSize: fontSize(11) }
            }
            Rectangle {
                visible: root.favorite
                anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 8
                width: 30; height: 30; radius: 15; color: MovieStyle.background
                MovieIcon { anchors.centerIn: parent; name: "star-filled"; width: 18; height: 18 }
            }
        }
        MovieText {
            Layout.fillWidth: true; Layout.preferredHeight: 34
            text: root.text; font.family: MovieStyle.fontFamily; font.pixelSize: fontSize(13); maximumLineCount: 2
            wrapMode: Text.Wrap; verticalAlignment: Text.AlignTop
        }
        MovieText {
            visible: !!root.subtitle
            Layout.fillWidth: true; Layout.preferredHeight: visible ? 18 : 0
            text: root.subtitle; color: MovieStyle.muted; font.family: MovieStyle.fontFamily; font.pixelSize: fontSize(11)
        }
    }
}
