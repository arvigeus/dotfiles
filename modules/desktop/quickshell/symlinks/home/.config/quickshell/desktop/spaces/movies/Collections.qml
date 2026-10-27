import "../../ui"
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollArea {
    id: root

    property var sections: []
    property bool loading: false
    property bool loaded: false
    property string error: ""

    signal activated(var title)

    function fontSize(value) {
        return Math.round(value * MovieStyle.fontSize / 14);
    }

    clip: true
    contentWidth: availableWidth

    ColumnLayout {
        width: parent.width
        spacing: 18

        MovieText {
            visible: !!root.error
            text: root.error
            color: MovieStyle.danger
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }

        MovieText {
            visible: root.loaded && !root.loading && !root.error && !root.sections.length
            text: "No collections or recommendations available."
            color: MovieStyle.muted
        }

        Repeater {
            model: root.sections

            ColumnLayout {
                id: section

                required property var modelData

                Layout.fillWidth: true
                spacing: 8

                MovieText {
                    text: modelData.label
                    font.family: MovieStyle.fontFamily
                    font.pixelSize: fontSize(18)
                    font.bold: true
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 10

                    Repeater {
                        model: modelData.items

                        Poster {
                            required property var modelData

                            objectName: section.modelData.label === "Recommended" ? "recommendedCollectionCard" : "relatedCollectionCard"
                            width: 138
                            height: 252
                            title: modelData
                            subtitle: modelData.relation || String(modelData.year || "")
                            onClicked: root.activated(modelData)
                        }
                    }
                }
            }
        }
    }
}
