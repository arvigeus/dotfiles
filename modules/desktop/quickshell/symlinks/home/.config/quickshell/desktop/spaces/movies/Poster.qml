import "../../ui"
import QtQuick

ArtworkCard {
    property var title: ({})

    text: title.title || ""
    imageSource: title.poster || ""
    fallbackIcon: title.kind === "tv" ? "tv" : "film"
}
