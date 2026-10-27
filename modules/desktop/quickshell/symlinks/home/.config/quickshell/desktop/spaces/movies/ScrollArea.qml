import "../../ui"
import QtQuick
import QtQuick.Controls

ScrollView {
    id: root

    WheelScroll {
        parent: root.contentItem
        view: root.contentItem
    }

    ScrollBar.vertical: MovieScrollBar {}

    ScrollBar.horizontal: MovieScrollBar {}
}
