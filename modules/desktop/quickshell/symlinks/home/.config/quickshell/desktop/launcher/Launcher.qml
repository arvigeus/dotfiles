pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import "../ui"
import "Search.js" as Search

InteractionWindow {
    id: root

    property string errorMessage: ""
    property bool launching: false
    property int session: 0
    property string searchQuery: ""
    // The Enter target and the query it belongs to. A new query selects its best
    // match; favorite and catalogue changes keep the same application selected.
    property string selectedId: ""
    property string selectionQuery: ""
    property bool pointerPositionKnown: false
    property point lastPointerPosition: Qt.point(0, 0)
    readonly property var favoriteIds: favorites.ids
    readonly property var candidates: Search.catalogue(DesktopEntries.applications.values)
    readonly property var matches: Search.matches(candidates, searchQuery, favoriteIds)

    Favorites {
        id: favorites
    }

    WlrLayershell.namespace: "desktop-launcher"
    initialFocus: search

    onOpenedChanged: {
        if (opened) {
            session++;
            pointerPositionKnown = false;
            selectedId = "";
            search.text = "";
            search.submit();
            errorMessage = "";
            Qt.callLater(root.resetSelection);
        }
    }
    // Let ScriptModel reconcile identities before assigning the new selection.
    onMatchesChanged: Qt.callLater(root.resetSelection)

    function select(index: int): void {
        results.currentIndex = index;
        selectedId = matches[index]?.id ?? "";
    }

    function resetSelection(): void {
        const kept = searchQuery === selectionQuery ? matches.findIndex(entry => entry.id === selectedId) : -1;
        selectionQuery = searchQuery;
        select(matches.length ? Math.max(0, kept) : -1);
        if (results.currentIndex > 0)
            results.positionViewAtIndex(results.currentIndex, ListView.Contain);
        else
            results.positionViewAtBeginning();
    }

    // Keys can arrive before the debounced query. Apply it first, so typing and
    // pressing Enter at once opens the typed query's best match.
    function applyQuery(): void {
        if (search.text === searchQuery)
            return;
        search.submit();
        resetSelection();
    }

    function toggleFavorite(id: string): void {
        if (DesktopEntries.applications.values.some(entry => entry.id === id))
            favorites.toggle(id);
    }

    GlobalShortcut {
        appid: "desktop"
        name: "launcher"
        description: "Open or close application search"
        onPressed: root.toggle()
    }

    function moveSelection(delta: int): void {
        applyQuery();
        if (!matches.length)
            return;
        select(Math.max(0, Math.min(matches.length - 1, results.currentIndex + delta)));
        results.positionViewAtIndex(results.currentIndex, ListView.Contain);
    }

    function updatePointerSelection(position: point): void {
        const moved = pointerPositionKnown && (position.x !== lastPointerPosition.x || position.y !== lastPointerPosition.y);
        lastPointerPosition = position;
        pointerPositionKnown = true;
        if (!moved || launching || results.dragging || resultsScrollBar.pressed)
            return;

        const local = results.mapFromItem(root.contentItem, position.x, position.y);
        if (local.x < 0 || local.y < 0 || local.x >= results.width || local.y >= results.height)
            return;
        const scrollbarPoint = resultsScrollBar.mapFromItem(root.contentItem, position.x, position.y);
        if (resultsScrollBar.visible && resultsScrollBar.size < 1 && resultsScrollBar.contains(scrollbarPoint))
            return;
        const index = results.indexAt(results.contentX + local.x, results.contentY + local.y);
        if (index >= 0)
            select(index);
    }

    HoverHandler {
        parent: root.contentItem
        enabled: root.visible
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        blocking: false
        // Observe the fixed window, not moving delegates. Mapping establishes a
        // baseline; only pointer motion can replace the keyboard's Enter target.
        onPointChanged: if (point.id >= 0)
            root.updatePointerSelection(point.position)
        onHoveredChanged: if (!hovered)
            root.pointerPositionKnown = false
    }

    function activate(index: int): void {
        if (launching || index < 0 || index >= matches.length)
            return;
        const entry = matches[index];
        if (!DesktopEntries.applications.values.includes(entry))
            return;
        errorMessage = "";
        launch.applicationName = entry.name;
        launch.launchSession = session;
        launching = true;
        // uwsm parses the entry (Terminal, Path, field codes) and starts it as its
        // own service, so it outlives desktop-shell.service restarts and the
        // command returns once the app started. uwsm resolves only standard IDs;
        // others, such as Steam or Wine names with spaces, go by file path.
        if (/^[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(entry.id))
            launch.exec(Apps.command([entry.id + ".desktop"]));
        else
            launch.exec(["python3", Quickshell.shellPath("launcher/entry_path.py"), entry.id, ...Apps.command([])]);
    }

    Process {
        id: launch
        property string applicationName: ""
        property int launchSession: 0
        stderr: StdioCollector {
            id: launchErrors
        }
        onExited: (exitCode, exitStatus) => {
            root.launching = false;
            if (launchSession !== root.session || !root.opened)
                return;
            if (exitCode === 0 && exitStatus === 0) {
                root.dismiss();
                return;
            }
            // Piped uwsm output carries journal priority prefixes such as "<3>".
            const detail = launchErrors.text.replace(/^<[0-7]>/gm, "").trim();
            // Fill the name last: a "%1" inside it must not receive the detail.
            root.errorMessage = qsTr("Could not open %1.").arg(applicationName) + (detail ? " " + detail : "");
        }
        // FailedToStart does not emit exited in Quickshell 0.3.2.
        onRunningChanged: if (!running)
            Qt.callLater(() => {
                if (!root.launching)
                    return;
                root.launching = false;
                if (launch.launchSession === root.session && root.opened)
                    root.errorMessage = qsTr("Application launching is unavailable. Check the desktop shell logs.");
            })
    }

    Surface {
        id: card
        width: Math.min(620, Math.max(0, root.width - Theme.paddingLarge * 2))
        height: Math.min(600, Math.max(0, root.height - y - Theme.paddingLarge))
        x: (root.width - width) / 2
        y: Math.max(Theme.paddingLarge, Math.min(root.height * 0.14, 160))

        // Consume blank card clicks before they reach the outside dismissal area.
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.padding
            spacing: Theme.gap

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.spacingMedium
                Layout.rightMargin: Theme.spacingMedium
                // The field's padding completes the same icon-to-text gap as a result row.
                spacing: Theme.spacingSmall
                Item {
                    Layout.preferredWidth: 32
                    Layout.preferredHeight: 32
                    Icon {
                        anchors.centerIn: parent
                        name: "search"
                    }
                }
                SearchInput {
                    id: search
                    objectName: "applicationSearch"
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.pillHeight
                    placeholderText: qsTr("Search applications…")
                    leftPadding: Theme.spacingMedium
                    rightPadding: Theme.controlHeight + 4
                    debounceInterval: 100
                    background: Rectangle {
                        radius: Theme.controlRadius
                        color: Theme.background
                        border.color: search.activeFocus ? Theme.accent : Theme.border
                    }
                    onSearchRequested: query => root.searchQuery = query
                    onTextChanged: root.errorMessage = ""
                    onAccepted: {
                        root.applyQuery();
                        root.activate(results.currentIndex);
                    }
                    Keys.onUpPressed: root.moveSelection(-1)
                    Keys.onDownPressed: root.moveSelection(1)
                    Keys.onPressed: event => {
                        if (event.key === Qt.Key_D && event.modifiers === Qt.ControlModifier) {
                            root.applyQuery();
                            const entry = root.matches[results.currentIndex];
                            if (entry && !root.launching)
                                root.toggleFavorite(entry.id);
                            event.accepted = true;
                        }
                    }
                }
            }

            ScrollListView {
                id: results
                objectName: "applicationResults"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: Theme.spacingSmall
                // An unmapped PanelWindow uses placeholder geometry. Build rows
                // only while mapped, avoiding icon work at invalid hidden sizes.
                model: ScriptModel {
                    values: root.visible ? root.matches : []
                }
                currentIndex: -1
                ScrollBar.vertical: ScrollBar {
                    id: resultsScrollBar
                }

                delegate: Button {
                    id: resultButton
                    required property DesktopEntry modelData
                    required property int index
                    width: results.width
                    height: 54
                    padding: Theme.spacingMedium
                    hoverEnabled: true
                    focusPolicy: Qt.NoFocus
                    // Always show the Enter target, including the initial first result.
                    readonly property bool rowHighlighted: ListView.isCurrentItem
                    // Native catalogue removals can clear an entry before its row is disposed.
                    text: modelData?.name || ""
                    enabled: !root.launching
                    onPressed: root.select(index)
                    onClicked: root.activate(index)
                    background: ButtonBackground {
                        highlighted: resultButton.rowHighlighted
                    }
                    contentItem: RowLayout {
                        spacing: Theme.gap
                        AppIcon {
                            icon: resultButton.modelData?.icon || ""
                            Layout.preferredWidth: 32
                            Layout.preferredHeight: 32
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            ShellText {
                                Layout.fillWidth: true
                                text: resultButton.text
                                elide: Text.ElideRight
                            }
                            ShellText {
                                Layout.fillWidth: true
                                text: resultButton.modelData?.genericName || resultButton.modelData?.id || ""
                                color: Theme.muted
                                font.pixelSize: Theme.smallFontSize
                                elide: Text.ElideRight
                            }
                        }
                        Button {
                            id: favoriteButton
                            objectName: "favorite-" + (resultButton.modelData?.id || "")
                            Layout.preferredWidth: Theme.controlHeight
                            Layout.preferredHeight: Theme.controlHeight
                            padding: Theme.spacingMedium
                            hoverEnabled: true
                            focusPolicy: Qt.NoFocus
                            readonly property bool favorite: root.favoriteIds.includes(resultButton.modelData?.id)
                            text: favorite ? qsTr("Remove %1 from favorites").arg(resultButton.text) : qsTr("Add %1 to favorites").arg(resultButton.text)
                            PassiveToolTip {
                                target: favoriteButton
                            }
                            onPressed: root.select(resultButton.index)
                            onClicked: root.toggleFavorite(resultButton.modelData?.id || "")
                            contentItem: Icon {
                                name: favoriteButton.favorite ? "star-filled" : "star"
                                color: resultButton.rowHighlighted ? Theme.accent : Theme.muted
                            }
                            background: null
                        }
                    }
                }

                ShellText {
                    anchors.centerIn: parent
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    color: Theme.muted
                    visible: !root.matches.length
                    text: search.text.trim() ? qsTr("No matching applications.") : qsTr("No applications available.")
                }
            }

            ShellText {
                Layout.fillWidth: true
                visible: root.errorMessage.length > 0
                text: root.errorMessage
                color: Theme.danger
                font.pixelSize: Theme.smallFontSize
                wrapMode: Text.WordWrap
            }
        }
    }
}
