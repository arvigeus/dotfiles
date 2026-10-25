import QtQuick

Rectangle {
    id: root
    property var cacheService: ImageCache
    property url source: ""
    property string ownerKey: ""
    property url poster: ""
    readonly property bool usingPoster: artwork.usingPreview
    readonly property bool loading: artwork.loading
    property bool gridMode: false
    property real readingEdge: 0.7
    color: MovieStyle.background
    ProgressiveImage {
        id: artwork
        anchors.fill: parent
        cacheService: root.cacheService
        source: root.source
        previewSource: root.poster
        ownerKey: root.ownerKey
        retainPreviousFor: 1000
        imageWidth: Math.max(1920, Math.ceil(root.width * 1.5))
        fullImageObjectName: "movieBackdropImage"
        previewImageObjectName: "moviePosterBackdrop"
        opacity: 0.9
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            // Shade the actual reading column while leaving the other side open.
            GradientStop { position: 0; color: root.gridMode ? "#4009090b" : "#cc09090b" }
            GradientStop { position: root.gridMode ? 0.45 : root.readingEdge; color: root.gridMode ? "#4d09090b" : "#b309090b" }
            GradientStop { position: root.gridMode ? 0.55 : Math.min(0.97, root.readingEdge + 0.18); color: root.gridMode ? "#b309090b" : "#6609090b" }
            GradientStop { position: 1; color: root.gridMode ? "#cc09090b" : "#2609090b" }
        }
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: "#8009090b" }
            GradientStop { position: 0.25; color: "#0009090b" }
            GradientStop { position: 0.7; color: "#3309090b" }
            GradientStop { position: 1; color: "#c409090b" }
        }
    }
}
