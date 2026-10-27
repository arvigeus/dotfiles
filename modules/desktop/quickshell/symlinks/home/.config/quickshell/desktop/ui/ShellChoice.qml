import QtQuick
import QtQuick.Controls
import "."

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
    delegate: ShellMenuItem {
        required property int index
        width: choices.width
        text: root.textAt(index)
        marked: root.currentIndex === index
        highlighted: root.highlightedIndex === index || hovered
        Accessible.checkable: true
        Accessible.checked: marked
    }
    popup: Popup {
        popupType: Popup.Item
        y: root.height + 4
        width: root.width
        padding: 6
        margins: 8
        implicitHeight: Math.min(choices.contentHeight + topPadding + bottomPadding, 360, Math.max(0, (Overlay.overlay?.height ?? 376) - 16))
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        contentItem: ScrollListView {
            id: choices
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            highlightMoveDuration: 0
            ScrollBar.vertical: ScrollBar {}
        }
        background: Surface {
            color: Theme.background
            radius: Theme.controlRadius
        }
    }
    background: Rectangle {
        color: Theme.surface
        radius: Theme.controlRadius
        border.width: 1
        border.color: root.visualFocus ? Theme.accent : Theme.border
    }
}
