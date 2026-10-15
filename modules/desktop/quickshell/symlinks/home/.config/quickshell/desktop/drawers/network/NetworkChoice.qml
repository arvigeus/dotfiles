import QtQuick
import QtQuick.Controls
import "../../ui"

ComboBox {
    id: root
    implicitHeight: Theme.controlHeight + 4
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSize
    palette.text: Theme.text
    palette.buttonText: Theme.text
    palette.window: Theme.raised
    palette.base: Theme.surface
    palette.highlight: Theme.accentSurface
    palette.highlightedText: Theme.text
    background: Rectangle {
        color: Theme.surface
        radius: Theme.controlRadius
        border.width: 1
        border.color: root.visualFocus ? Theme.accent : Theme.border
    }
}
