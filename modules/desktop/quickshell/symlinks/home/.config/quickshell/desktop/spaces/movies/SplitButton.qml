import QtQuick
import "../../ui"
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: root
    property string text: ""
    property string iconName: "play"
    property bool busy: false
    property bool showLoading: true
    property var options: []
    property int currentIndex: 0
    property alias popup: menu
    signal triggered(int index)
    spacing: 0
    HoverHandler { id: groupHover }
    MovieButton {
        id: primary
        contentItem: RowLayout { spacing: 8; MovieIcon { name: root.iconName; color: MovieStyle.accentText } MovieText { text: root.text; color: MovieStyle.accentText } }
        text: root.text; iconName: root.iconName
        Accessible.description: root.busy ? "Opening player" : ""
        onClicked: root.triggered(root.currentIndex)
        MovieSpinner {
            foreground: MovieStyle.accentText
            anchors.centerIn: parent
            width: 24; height: 24
            visible: root.showLoading && root.busy; running: visible; z: 1
        }
        background: Rectangle {
            radius: MovieStyle.controlRadius
            topRightRadius: arrow.visible ? 0 : MovieStyle.controlRadius
            bottomRightRadius: arrow.visible ? 0 : MovieStyle.controlRadius
            color: primary.down || arrow.down ? Qt.darker(MovieStyle.accent, 1.2)
                  : groupHover.hovered ? Qt.lighter(MovieStyle.accent, 1.1) : MovieStyle.accent
            border.color: primary.activeFocus ? MovieStyle.text : "transparent"
            border.width: 2
        }
    }
    Binding { target: primary.contentItem; property: "opacity"; value: root.showLoading && root.busy ? 0 : 1 }
    MovieIconButton {
        id: arrow
        visible: root.options.length > 1
        iconName: "chevron-down"; text: "Choose " + root.text.toLowerCase()
        onClicked: menu.visible ? menu.close() : menu.open()
        background: Rectangle {
            radius: MovieStyle.controlRadius
            topLeftRadius: 0
            bottomLeftRadius: 0
            color: primary.down || arrow.down ? Qt.darker(MovieStyle.accent, 1.2)
                  : groupHover.hovered ? Qt.lighter(MovieStyle.accent, 1.1) : MovieStyle.accent
            border.color: arrow.activeFocus ? MovieStyle.text : "transparent"
            border.width: 2
        }
        Menu {
            id: menu
            popupType: Popup.Item
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
            y: arrow.height; width: Math.min(440,root.Window.width - 48)
            background: Rectangle { color: MovieStyle.surface; border.color: MovieStyle.border; radius: MovieStyle.controlRadius }
            Repeater {
                model: root.options
                MenuItem {
                    required property string modelData
                    required property int index
                    text: modelData
                    contentItem: MovieText { text: parent.text; color: parent.highlighted ? MovieStyle.accent : MovieStyle.text }
                    background: Rectangle { color: parent.highlighted ? MovieStyle.raised : "transparent" }
                    onTriggered: { root.currentIndex=index; root.triggered(index); }
                }
            }
        }
    }
}
