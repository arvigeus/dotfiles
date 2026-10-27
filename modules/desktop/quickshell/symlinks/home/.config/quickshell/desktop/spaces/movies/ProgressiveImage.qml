import QtQuick

// Both layers use the same cache: previews appear while the original is loading.
Item {
    id: root

    property var cacheService: ImageCache
    property url source: ""
    property url previewSource: ""
    property string ownerKey: ""
    property int retainPreviousFor: 0
    property int fillMode: Image.PreserveAspectCrop
    property int horizontalAlignment: Image.AlignHCenter
    property int imageWidth: 2560
    property string fullImageObjectName: "progressiveFullImage"
    property string previewImageObjectName: "progressivePreviewImage"
    readonly property bool usingPreview: !original.hasImage && preview.hasImage
    readonly property bool hasImage: original.hasImage || preview.hasImage
    readonly property bool loading: original.loading || (!original.hasImage && preview.loading)
    readonly property bool transitioning: original.transitioning || preview.transitioning
    readonly property url displayedSource: original.hasImage ? original.displayedSource : preview.displayedSource
    readonly property real sourceAspectRatio: original.hasImage ? original.sourceAspectRatio : preview.sourceAspectRatio
    readonly property string failedSource: hasImage ? "" : original.failedSource || preview.failedSource

    CrossfadeImage {
        id: preview

        objectName: root.previewImageObjectName
        anchors.fill: parent
        cacheService: root.cacheService
        source: root.visible ? root.previewSource : ""
        resetOnSourceChange: true
        imageWidth: root.imageWidth
        fillMode: root.fillMode
        horizontalAlignment: root.horizontalAlignment
        opacity: root.usingPreview ? 1 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: 240
            }
        }
    }

    CrossfadeImage {
        id: original

        objectName: root.fullImageObjectName
        anchors.fill: parent
        cacheService: root.cacheService
        source: root.visible ? root.source : ""
        ownerKey: root.ownerKey
        staleAfter: root.retainPreviousFor
        resetOnSourceChange: root.retainPreviousFor === 0
        imageWidth: root.imageWidth
        fillMode: root.fillMode
        horizontalAlignment: root.horizontalAlignment
        opacity: original.hasImage ? 1 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: 240
            }
        }
    }
}
