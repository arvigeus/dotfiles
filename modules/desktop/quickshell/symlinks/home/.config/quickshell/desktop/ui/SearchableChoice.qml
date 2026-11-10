pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// The caller binds currentIndex and applies activated(index), keeping selection
// independent of the filtered list's row numbers.
ShellChoice {
    id: root
    property string searchRole: ""
    property string searchPlaceholder: qsTr("Search")
    readonly property var matchingIndices: {
        const terms = search.text.trim().toLowerCase().split(/\s+/).filter(Boolean);
        return Array.from({
            length: count
        }, (_, index) => index).filter(index => {
            const text = (textAt(index) + " " + (searchRole ? model[index]?.[searchRole] ?? "" : "")).toLowerCase();
            return terms.every(term => text.includes(term));
        });
    }
    function choose(index: int): void {
        if (index >= 0 && index < matchingIndices.length) {
            activated(matchingIndices[index]);
            popup.close();
        }
    }
    popup: Popup {
        popupType: Popup.Item
        y: root.height + 4
        width: root.width
        padding: 6
        margins: 8
        focus: true
        implicitHeight: Math.min(search.implicitHeight + Math.max(choices.contentHeight, empty.implicitHeight) + 6 + topPadding + bottomPadding, 360, Math.max(0, (Overlay.overlay?.height ?? 376) - 16))
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        onOpened: {
            search.clear();
            choices.currentIndex = Math.max(0, root.matchingIndices.indexOf(root.currentIndex));
            choices.positionViewAtIndex(choices.currentIndex, ListView.Contain);
            search.forceActiveFocus(Qt.PopupFocusReason);
        }
        contentItem: ColumnLayout {
            spacing: 6
            InputField {
                id: search
                objectName: root.objectName + "Search"
                Layout.fillWidth: true
                placeholderText: root.searchPlaceholder
                clearAccessibleName: qsTr("Clear search")
                onTextChanged: choices.currentIndex = 0
                Keys.onDownPressed: choices.incrementCurrentIndex()
                Keys.onUpPressed: choices.decrementCurrentIndex()
                Keys.onReturnPressed: root.choose(choices.currentIndex)
                Keys.onEnterPressed: root.choose(choices.currentIndex)
            }
            ScrollListView {
                id: choices
                objectName: root.objectName + "Results"
                visible: count > 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                implicitHeight: contentHeight
                model: root.popup.visible ? root.matchingIndices : []
                highlightMoveDuration: 0
                ScrollBar.vertical: ScrollBar {}
                delegate: ShellMenuItem {
                    required property int index
                    required property int modelData
                    objectName: root.objectName + "Option:" + modelData
                    width: choices.width
                    text: root.textAt(modelData)
                    marked: root.currentIndex === modelData
                    highlighted: ListView.isCurrentItem || hovered
                    Accessible.checkable: true
                    Accessible.checked: marked
                    onHoveredChanged: if (hovered)
                        choices.currentIndex = index
                    onClicked: root.choose(index)
                }
            }
            ShellText {
                id: empty
                objectName: root.objectName + "NoMatches"
                Layout.fillWidth: true
                visible: !choices.count
                text: qsTr("No matches")
                color: Theme.muted
                padding: 6
            }
        }
        background: Surface {
            color: Theme.background
            radius: Theme.controlRadius
        }
    }
}
