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
    property string selectionToRestore: ""
    property bool pointerPositionKnown: false
    property point lastPointerPosition: Qt.point(0, 0)
    readonly property var favoriteIds: favorites.ids
    readonly property var candidates: Search.catalogue(DesktopEntries.applications.values)
    readonly property var matches: Search.matches(candidates, search.text, favoriteIds)

    Favorites { id: favorites }

    WlrLayershell.namespace: "desktop-launcher"
    initialFocus: search

    onOpenedChanged: {
        if (opened) {
            session++;
            pointerPositionKnown = false;
            selectionToRestore = "";
            search.text = "";
            errorMessage = "";
            Qt.callLater(root.resetSelection);
        }
    }
    // Let ScriptModel reconcile identities before assigning the new selection.
    onMatchesChanged: Qt.callLater(root.resetSelection)

    function resetSelection(): void {
        const wanted = selectionToRestore;
        selectionToRestore = "";
        const index = wanted ? matches.findIndex(entry => entry.id === wanted) : 0;
        results.currentIndex = matches.length ? Math.max(0, index) : -1;
        if (results.currentIndex > 0)
            results.positionViewAtIndex(results.currentIndex, ListView.Contain);
        else
            results.positionViewAtBeginning();
    }

    function toggleFavorite(id: string): void {
        if (!DesktopEntries.applications.values.some(entry => entry.id === id))
            return;
        // Reordering favorites must not change the next Enter target.
        selectionToRestore = matches[results.currentIndex]?.id || "";
        favorites.toggle(id);
        Qt.callLater(root.resetSelection);
    }

    GlobalShortcut {
        appid: "desktop"
        name: "launcher"
        description: "Open or close application search"
        onPressed: root.toggle()
    }

    function moveSelection(delta: int): void {
        if (!matches.length)
            return;
        results.currentIndex = Math.max(0, Math.min(matches.length - 1, results.currentIndex + delta));
        results.positionViewAtIndex(results.currentIndex, ListView.Contain);
    }

    function updatePointerSelection(position: point): void {
        const moved = pointerPositionKnown
            && (position.x !== lastPointerPosition.x || position.y !== lastPointerPosition.y);
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
            results.currentIndex = index;
    }

    HoverHandler {
        parent: root.contentItem
        enabled: root.visible
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        blocking: false
        // Observe the fixed window, not moving delegates. Mapping establishes a
        // baseline; only pointer motion can replace the keyboard's Enter target.
        onPointChanged: if (point.id >= 0) root.updatePointerSelection(point.position)
        onHoveredChanged: if (!hovered) root.pointerPositionKnown = false
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
        // GIO handles Terminal, Path, field codes and D-Bus activation. Pass the
        // ID as one argument; do not parse Exec or interpolate a shell command.
        launch.exec(["/usr/bin/gtk-launch", "--", entry.id]);
    }

    Process {
        id: launch
        property string applicationName: ""
        property int launchSession: 0
        stderr: StdioCollector { id: launchErrors }
        onExited: (exitCode, exitStatus) => {
            root.launching = false;
            if (launchSession !== root.session || !root.opened)
                return;
            if (exitCode === 0 && exitStatus === 0) {
                root.dismiss();
            } else {
                root.errorMessage = qsTr("Could not open %1. %2")
                    .arg(applicationName).arg(launchErrors.text.trim());
            }
        }
        // FailedToStart does not emit exited in Quickshell 0.3.2.
        onRunningChanged: if (!running) Qt.callLater(() => {
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
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }

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
                    Icon { anchors.centerIn: parent; name: "search" }
                }
                TextField {
                    id: search
                    objectName: "applicationSearch"
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.pillHeight
                    placeholderText: qsTr("Search applications…")
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize
                    color: Theme.text
                    placeholderTextColor: Theme.muted
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.accentText
                    leftPadding: Theme.spacingMedium
                    rightPadding: Theme.gap
                    background: Rectangle {
                        radius: Theme.controlRadius
                        color: Theme.background
                        border.color: search.activeFocus ? Theme.accent : Theme.border
                    }
                    onTextChanged: {
                        root.errorMessage = "";
                        root.selectionToRestore = "";
                    }
                    onAccepted: root.activate(results.currentIndex)
                    Keys.onUpPressed: root.moveSelection(-1)
                    Keys.onDownPressed: root.moveSelection(1)
                    Keys.onPressed: event => {
                        if (event.key === Qt.Key_D && event.modifiers === Qt.ControlModifier) {
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
                model: ScriptModel { values: root.visible ? root.matches : [] }
                currentIndex: -1
                ScrollBar.vertical: ScrollBar { id: resultsScrollBar }

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
                    onPressed: results.currentIndex = index
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
                            text: favorite ? qsTr("Remove %1 from favorites").arg(resultButton.text)
                                : qsTr("Add %1 to favorites").arg(resultButton.text)
                            PassiveToolTip { target: favoriteButton }
                            onPressed: results.currentIndex = resultButton.index
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
