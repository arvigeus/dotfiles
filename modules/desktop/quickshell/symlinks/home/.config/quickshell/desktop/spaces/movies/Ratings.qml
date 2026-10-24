import QtQuick
import "../../ui"
import "RatingLinks.js" as RatingLinks

Flow {
    id: root
    property var host
    property var ratings: []
    property var title: ({})
    spacing: 18
    function icon(r) {
        const source = RatingLinks.source(r);
        const score = parseFloat(r.value);
        if (source === "rt") return score >= 75 ? "rt_certified" : score >= 60 ? "rt_fresh" : "rt_rotten";
        if (source === "rt_audience") return score >= 90 ? "rt_audience_hot" : score >= 60 ? "rt_audience_positive" : "rt_audience_negative";
        return ({imdb:"imdb", myanimelist:"mal", tmdb:"tmdb", metacritic:"metacritic"})[source] || "";
    }
    Repeater {
        model: RatingLinks.ordered(root.ratings).filter(r => !!root.icon(r))
        MovieButton {
            id: ratingButton
            required property var modelData
            readonly property string ratingIcon: root.icon(modelData)
            objectName: "rating:" + RatingLinks.source(modelData)
            text: modelData.source + ": " + modelData.value
            Accessible.name: text
            implicitWidth: ratingContent.implicitWidth + leftPadding + rightPadding; implicitHeight: 36
            padding: 4
            onClicked: Browser.open(RatingLinks.page(modelData, root.title), root.title.kind === "tv" ? "series" : "movies", "", root.host)
            contentItem: Row {
                id: ratingContent
                spacing: 6
                Image {
                    objectName: "ratingArtwork"
                    source: Qt.resolvedUrl("ratings/rating_" + ratingButton.ratingIcon + (ratingButton.ratingIcon === "mal" ? ".svg" : ".png"))
                    width: 30; height: 30
                    sourceSize.width: 60; sourceSize.height: 60
                    fillMode: Image.PreserveAspectFit
                }
                MovieText { anchors.verticalCenter: parent.verticalCenter; text: String(ratingButton.modelData.value); font.bold: true; font.pixelSize: MovieStyle.fontSize + 2 }
            }
        }
    }
}
