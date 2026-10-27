import QtQuick
import QtQuick.Controls

ComboBox {
    id: root

    implicitHeight: MovieStyle.controlHeight + 4
    leftPadding: 12
    rightPadding: 28
    font.family: MovieStyle.fontFamily
    font.pixelSize: MovieStyle.fontSize
    palette.text: MovieStyle.text
    palette.buttonText: MovieStyle.text
    palette.window: MovieStyle.surface
    palette.base: MovieStyle.surface
    palette.highlight: MovieStyle.accentSurface
    palette.highlightedText: MovieStyle.text

    contentItem: MovieText {
        text: root.displayText
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: MovieIcon {
        name: "chevron-down"
        x: root.width - width - 8
        y: (root.height - height) / 2
        width: 16
        height: 16
    }

    background: Rectangle {
        color: "#c0141117"
        radius: MovieStyle.controlRadius
        border.width: 1
        border.color: root.visualFocus ? MovieStyle.accent : MovieStyle.border
    }

    delegate: ItemDelegate {
        required property var modelData
        required property int index

        width: root.popup.width
        highlighted: root.highlightedIndex === index

        contentItem: MovieText {
            text: root.textRole ? modelData[root.textRole] : modelData
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }

        background: Rectangle {
            color: parent.highlighted ? MovieStyle.accentSurface : "transparent"
        }
    }

    popup: Popup {
        y: root.height + 4
        width: root.width
        padding: 6
        implicitHeight: Math.min(contentItem.implicitHeight + 12, 360)

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex

            ScrollBar.vertical: MovieScrollBar {}
        }

        background: Rectangle {
            color: MovieStyle.surface
            radius: MovieStyle.controlRadius
            border.color: MovieStyle.border
        }
    }
}
