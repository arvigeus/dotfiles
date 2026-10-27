import QtQuick
import QtQuick.Controls
import "../movies"

AbstractButton {
    id: root
    implicitWidth: contentItem.implicitWidth
    implicitHeight: contentItem.implicitHeight
    hoverEnabled: true
    contentItem: MovieText {
        text: root.text
        color: root.hovered || root.visualFocus ? MovieStyle.text : MovieStyle.muted
        font.underline: root.enabled && (root.hovered || root.visualFocus)
        elide: Text.ElideRight
    }
    background: Item {}
}
