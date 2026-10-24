import QtQuick
import "../../ui"
import QtQuick.Controls

ScrollView {
    id: root
    ScrollBar.vertical: MovieScrollBar {}
    ScrollBar.horizontal: MovieScrollBar {}
    WheelScroll { parent: root.contentItem; view: root.contentItem }
}
