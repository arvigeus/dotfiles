import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"
import "../movies"

Popup {
    id: root
    property var options: []
    property var selectedNames: []
    property bool multiple: false
    property bool loading: false
    property string error: ""
    property string placeholder: "Search…"
    readonly property var matches: options.filter(item => item.name.toLowerCase().includes(query.text.trim().toLowerCase()))
    signal chosen(string name)
    signal retry
    width: 320
    height: 420
    padding: 10
    onOpened: {
        query.clear();
        query.forceActiveFocus();
        choices.currentIndex = 0;
    }
    background: Rectangle {
        color: MovieStyle.surface
        radius: MovieStyle.controlRadius
        border.color: MovieStyle.border
    }
    contentItem: ColumnLayout {
        spacing: 8
        MovieInput {
            id: query
            Layout.fillWidth: true
            placeholderText: root.placeholder
            Accessible.name: root.placeholder
            Keys.onDownPressed: choices.forceActiveFocus()
            onAccepted: if (choices.count)
                root.chosen(root.matches[Math.max(0, choices.currentIndex)].name)
        }
        MovieText {
            visible: root.loading
            text: "Loading…"
            color: MovieStyle.muted
        }
        MovieText {
            visible: !!root.error
            Layout.fillWidth: true
            text: root.error
            wrapMode: Text.Wrap
            color: MovieStyle.danger
        }
        MovieButton {
            visible: !!root.error
            text: "Retry"
            onClicked: root.retry()
        }
        ListView {
            id: choices
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.matches
            spacing: 2
            activeFocusOnTab: true
            keyNavigationEnabled: true
            Keys.onReturnPressed: if (currentIndex >= 0)
                root.chosen(root.matches[currentIndex].name)
            Keys.onEnterPressed: if (currentIndex >= 0)
                root.chosen(root.matches[currentIndex].name)
            delegate: MovieButton {
                required property var modelData
                required property int index
                width: choices.width
                text: modelData.name || "All countries"
                highlighted: root.selectedNames.includes(modelData.name) || (choices.activeFocus && choices.currentIndex === index)
                Accessible.name: text
                Accessible.description: root.selectedNames.includes(modelData.name) ? "Selected" : ""
                onClicked: {
                    choices.currentIndex = index;
                    root.chosen(modelData.name);
                }
            }
            WheelScroll {
                view: choices
            }
            ScrollBar.vertical: MovieScrollBar {}
        }
        MovieText {
            visible: !root.loading && !root.error && !choices.count
            text: "No matches."
            color: MovieStyle.muted
        }
        MovieButton {
            visible: root.multiple
            text: "Done"
            Layout.alignment: Qt.AlignRight
            onClicked: root.close()
        }
    }
}
