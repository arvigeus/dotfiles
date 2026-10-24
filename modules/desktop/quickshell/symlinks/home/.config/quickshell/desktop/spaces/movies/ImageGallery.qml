import QtQuick
import "../../ui"
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    property var cacheService: ImageCache
    objectName: "movieGallery"
    property var images: []
    property string title: "Images"
    property int currentIndex: 0
    property bool zoomed: false
    property var returnFocus: null
    readonly property var currentImage: images[currentIndex] || ({})
    readonly property string imageSource: typeof currentImage === "string" ? currentImage : currentImage.url || ""
    width: parent.width
    height: parent.height
    // Keep the host's top-left hide control reachable outside the page.
    modal: false
    popupType: Popup.Item
    focus: true
    padding: 14
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    function show(items, index, caption) {
        returnFocus = root.parent && root.parent.Window.window ? root.parent.Window.window.activeFocusItem : null;
        images = items || [];
        currentIndex = Math.max(0, Math.min(index || 0, images.length - 1));
        title = caption || "Images";
        zoomed = false;
        open();
    }
    function step(delta) {
        if (images.length) currentIndex = (currentIndex + delta + images.length) % images.length;
    }
    onCurrentIndexChanged: { pan.contentX = 0; pan.contentY = 0; }
    onOpened: contentItem.forceActiveFocus()
    onClosed: {
        images = [];
        if (returnFocus) returnFocus.forceActiveFocus();
        returnFocus = null;
    }
    background: Rectangle { color: MovieStyle.background; border.color: MovieStyle.border; radius: MovieStyle.radius }
    contentItem: ColumnLayout {
        Keys.onPressed: event => {
            if (event.key === Qt.Key_Left) root.step(-1);
            else if (event.key === Qt.Key_Right) root.step(1);
            else if (event.key === Qt.Key_Home) root.currentIndex = 0;
            else if (event.key === Qt.Key_End) root.currentIndex = root.images.length - 1;
            else if (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal || event.key === Qt.Key_Minus) root.zoomed = !root.zoomed;
            else { event.accepted = false; return; }
            event.accepted = true;
        }
        RowLayout {
            Layout.fillWidth: true
            MovieText { text: root.title; Layout.fillWidth: true; elide: Text.ElideRight; font.bold: true }
            MovieText { text: root.images.length ? (root.currentIndex + 1) + " / " + root.images.length : ""; color: MovieStyle.muted }
            MovieButton { text: root.zoomed ? "Fit" : "Zoom"; onClicked: root.zoomed = !root.zoomed }
            MovieIconButton { iconName: "x"; text: "Close gallery"; onClicked: root.close() }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Flickable {
                id: pan
                anchors.fill: parent
                clip: true
                contentWidth: Math.max(width, fullImage.width)
                contentHeight: Math.max(height, fullImage.height)
                boundsBehavior: Flickable.StopAtBounds
                CachedImage { cacheService: root.cacheService;
                    id: fullImage
                    objectName: "galleryImage"
                    remoteSource: root.visible ? root.imageSource : ""
                    sourceSize.width: root.zoomed ? 3840 : 1920
                    asynchronous: true
                    fillMode: Image.PreserveAspectFit
                    width: root.zoomed ? Math.max(pan.width, implicitWidth) : pan.width
                    height: root.zoomed ? Math.max(pan.height, implicitHeight) : pan.height
                }
            }
            MovieSpinner { objectName: "gallerySpinner"; anchors.centerIn: parent; visible: running; running: fullImage.loadStatus === Image.Loading }
            MovieText { anchors.centerIn: parent; visible: fullImage.loadStatus === Image.Error; text: "This image could not load."; color: MovieStyle.muted }
            MovieIconButton { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; visible: root.images.length > 1; iconName: "chevron-left"; text: "Previous image"; highlighted: true; onClicked: root.step(-1) }
            MovieIconButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; visible: root.images.length > 1; iconName: "chevron-right"; text: "Next image"; highlighted: true; onClicked: root.step(1) }
        }
    }
}
