import "../../ui"
import QtQuick
import QtQuick.Controls

ListView {
    id: root

    property var cacheService: ImageCache
    property var images: []

    signal activated(int index)

    implicitHeight: 116
    orientation: ListView.Horizontal
    spacing: 8
    clip: true
    model: images
    keyNavigationEnabled: true
    activeFocusOnTab: true
    Keys.onReturnPressed: {
        if (currentIndex >= 0) {
            activated(currentIndex);
        }
    }
    Keys.onEnterPressed: {
        if (currentIndex >= 0) {
            activated(currentIndex);
        }
    }

    WheelScroll {
        view: root
        orientation: Qt.Horizontal
        verticalToHorizontal: true
        wheelStep: 300
    }

    ScrollBar.horizontal: MovieScrollBar {}

    delegate: Button {
        required property var modelData
        required property int index

        width: 185
        height: 108
        hoverEnabled: true
        Accessible.name: "View image " + (index + 1) + " of " + root.count
        onClicked: {
            root.currentIndex = index;
            root.activated(index);
        }

        background: Rectangle {
            color: MovieStyle.surface

            CrossfadeImage {
                cacheService: root.cacheService
                anchors.fill: parent
                anchors.margins: 2
                imageWidth: 400
                source: modelData.thumbnail || modelData.url || ""
            }

            Rectangle {
                anchors.fill: parent
                color: "transparent"
                border.width: 2
                border.color: parent.parent.activeFocus || (root.activeFocus && root.currentIndex === index) ? MovieStyle.accent : "transparent"
            }
        }
    }
}
