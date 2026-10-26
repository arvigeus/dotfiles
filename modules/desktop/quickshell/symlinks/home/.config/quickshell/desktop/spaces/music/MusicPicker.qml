import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"
import "../movies"

Popup {
    id: root
    objectName: "musicPicker"
    required property var service
    property bool discover: false
    property real maximumWidth: 380
    property string category: "artists"
    property var items: []
    property bool loading: false
    property bool hasMore: false
    property int offset: 0
    property int generation: 0
    property string error: ""
    signal chosen(var item)
    width: Math.min(380,maximumWidth)
    height: 440
    padding: 12
    background: Rectangle { color: MovieStyle.surface; radius: 6; border.color: MovieStyle.border }
    function show(kind) { category = kind; items = []; offset = 0; hasMore = false; open(); query.clear(); query.forceActiveFocus(); load(false); }
    function load(append) {
        if (!visible || (append && (loading || !hasMore))) return;
        const token = ++generation;
        error = "";
        if (discover && query.text.trim().length < 2) { items = []; hasMore = false; loading = false; return; }
        loading = true;
        service.request(discover ? "search-page" : "browse",{category:category,query:query.text.trim(),offset:append ? offset : 0,lane:"picker"},(result,failure) => {
            if (token !== generation) return;
            loading = false;
            if (failure) { error = failure; return; }
            items = append ? items.concat(result.items || []) : result.items || [];
            offset = result.limit || items.length; hasMore = !!result.hasMore;
            Qt.callLater(() => { if (hasMore && choices.contentHeight < choices.height) load(true); });
        });
    }
    onClosed: { ++generation; delay.stop(); loading = false; }
    Timer { id: delay; interval: 250; onTriggered: root.load(false) }
    contentItem: ColumnLayout {
        spacing: 8
        MovieInput { id: query; objectName: "musicPickerSearch"; Layout.fillWidth: true; placeholderText: "Search " + root.category + "…"; Accessible.name: placeholderText; onTextChanged: delay.restart(); onAccepted: root.load(false); Keys.onDownPressed: choices.forceActiveFocus() }
        ListView {
            id: choices; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 2; model: root.items; keyNavigationEnabled: true; activeFocusOnTab: true
            onContentYChanged: if (contentY + height > contentHeight - 300) root.load(true)
            Keys.onReturnPressed: if (currentIndex >= 0) { root.chosen(root.items[currentIndex]); root.close(); }
            delegate: MovieButton {
                required property var modelData
                required property int index
                width: choices.width; text: modelData.name || modelData.title || ""; highlighted: choices.activeFocus && choices.currentIndex === index
                onClicked: { root.chosen(modelData); root.close(); }
            }
            WheelScroll { view: choices }
            ScrollBar.vertical: MovieScrollBar {}
        }
        MovieText { Layout.fillWidth: true; wrapMode: Text.Wrap; color: MovieStyle.muted; visible: root.loading || !!root.error || !root.items.length; text: root.error || (root.loading ? "Loading…" : root.discover && query.text.trim().length < 2 ? "Type to search Apple Music." : "No matches.") }
    }
}
