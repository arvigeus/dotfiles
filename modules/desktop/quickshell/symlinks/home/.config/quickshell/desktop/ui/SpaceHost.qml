pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import "FocusNavigation.js" as FocusNavigation

InteractionWindow {
    id: root
    objectName: "spaceHost"
    readonly property var currentEntry: SpaceState.entries.find(entry => entry.id === SpaceState.currentId)
    readonly property var currentPage: instanceFor(SpaceState.currentId)?.item ?? null
    property var pendingCatalogueFocus: null
    property var navigateDesktop: direction => Hyprland.dispatch('function() hl.dispatch(hl.dsp.layout("focus ' + (direction < 0 ? 'l' : 'r') + '")) hl.dispatch(hl.dsp.layout("center")) hl.dispatch(hl.dsp.event("desktop-layout-changed")) end')
    initialFocus: currentPage?.initialFocus ?? hideButton
    escapeHandler: () => {
        if (!root.currentPage?.dismissTransient())
            root.dismiss();
    }
    Component.onCompleted: SpaceState.host = root
    Component.onDestruction: if (SpaceState.host === root)
        SpaceState.host = null
    onCurrentPageChanged: pendingCatalogueFocus = null
    onOpenedChanged: if (!opened)
        pendingCatalogueFocus = null

    function requestCatalogueFocus(): void {
        if (!opened || !currentPage)
            return;
        pendingCatalogueFocus = {
            page: currentPage,
            from: currentFocusItem()
        };
        Qt.callLater(applyCatalogueFocus);
    }
    function applyCatalogueFocus(): void {
        const request = pendingCatalogueFocus;
        if (!request || !opened || request.page !== currentPage)
            return;
        const target = currentPage.catalogueFocus;
        if (!target?.visible || !target.enabled)
            return;
        const focused = currentFocusItem();
        // Results may arrive after the user has moved into a search/filter.
        if (focused && focused !== request.from && focused.activeFocusOnTab && !FocusNavigation.belongsTo(target, focused)) {
            pendingCatalogueFocus = null;
            return;
        }
        pendingCatalogueFocus = null;
        target.forceActiveFocus(Qt.OtherFocusReason);
    }
    function stepTab(direction: int): void {
        const tabs = Array.from(currentPage?.navigationTabs ?? []).filter(tab => tab.visible && tab.enabled);
        if (!tabs.length) {
            stepFocus(direction);
            return;
        }
        const current = tabs.findIndex(tab => tab.highlighted);
        const next = current < 0 ? 0 : (current + direction + tabs.length) % tabs.length;
        tabs[next].clicked();
        requestCatalogueFocus();
    }
    function handleBumper(direction: int): void {
        const surface = interactionState.activeSurface;
        if (surface === root)
            stepTab(direction);
        else if (surface)
            surface.stepFocus(direction);
        else
            navigateDesktop(direction);
    }

    Instantiator {
        model: root.currentPage?.navigationTabs ?? []
        delegate: Connections {
            required property var modelData
            target: modelData
            function onClicked(): void {
                root.requestCatalogueFocus();
            }
        }
    }
    Connections {
        target: root.currentPage?.catalogueFocus ?? null
        ignoreUnknownSignals: true
        function onTargetChanged(): void {
            Qt.callLater(root.applyCatalogueFocus);
        }
        function onVisibleChanged(): void {
            Qt.callLater(root.applyCatalogueFocus);
        }
        function onEnabledChanged(): void {
            Qt.callLater(root.applyCatalogueFocus);
        }
        function onCountChanged(): void {
            Qt.callLater(root.applyCatalogueFocus);
        }
    }
    Shortcut {
        sequence: "Ctrl+PgUp"
        enabled: root.opened && root.visible
        onActivated: root.stepTab(-1)
    }
    Shortcut {
        sequence: "Ctrl+PgDown"
        enabled: root.opened && root.visible
        onActivated: root.stepTab(1)
    }

    function instanceFor(id) {
        for (let i = 0; i < instances.count; ++i) {
            const loader = instances.itemAt(i);
            if (loader?.modelData.id === id)
                return loader;
        }
        return null;
    }
    function deliver(id, payload) {
        const loader = instanceFor(id);
        if (!payload || !loader)
            return;
        loader.pendingPayload = payload;
        loader.deliverPending();
    }

    Rectangle {
        anchors.fill: parent
        color: "#09090b"
    }
    Item {
        id: backdropLayer
        objectName: "spaceBackdropLayer"
        anchors.fill: parent
    }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.paddingLarge
        spacing: Theme.padding
        Keys.priority: Keys.AfterItem
        Keys.onPressed: event => {
            event.accepted = root.opened && FocusNavigation.arrow(root.contentItem, root.currentFocusItem(), event);
        }
        RowLayout {
            Layout.fillWidth: true
            IconButton {
                id: hideButton
                objectName: "hideSpace"
                iconName: "x"
                text: qsTr("Hide %1").arg(root.currentEntry?.name ?? qsTr("space"))
                iconColor: "#ffffff"
                background: Rectangle {
                    radius: 6
                    color: hideButton.hovered || hideButton.visualFocus ? "#60e50914" : "transparent"
                }
                onClicked: root.dismiss()
            }
            Rectangle {
                objectName: "spaceToolbarSeparator"
                Layout.preferredWidth: 1
                Layout.preferredHeight: 24
                Layout.leftMargin: 8
                Layout.rightMargin: 12
                color: "#45ffffff"
            }
            Item {
                id: toolbarLayer
                objectName: "spaceToolbarLayer"
                Layout.fillWidth: true
                Layout.preferredHeight: root.currentPage?.toolbarHeight ?? 46
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Repeater {
                id: instances
                model: SpaceState.entries
                Loader {
                    id: instance
                    required property var modelData
                    // An open request waits for asynchronous creation; closing discards it.
                    property var pendingPayload: null
                    function deliverPending() {
                        const payload = pendingPayload;
                        if (!payload || !item)
                            return;
                        pendingPayload = null;
                        if (item.handleOpen)
                            item.handleOpen(payload);
                    }
                    anchors.fill: parent
                    active: SpaceState.runningIds.includes(modelData.id)
                    visible: root.opened && SpaceState.currentId === modelData.id
                    asynchronous: true
                    source: Qt.resolvedUrl(modelData.source)
                    onActiveChanged: if (!active)
                        pendingPayload = null
                    onLoaded: {
                        if ("backdropTarget" in item)
                            item.backdropTarget = backdropLayer;
                        if ("toolbarTarget" in item)
                            item.toolbarTarget = toolbarLayer;
                        // Late callbacks from a hidden or background Space must not
                        // hide, reopen or navigate whichever Space is presented now.
                        item.host = {
                            hide: () => {
                                if (instance.visible)
                                    SpaceState.hide();
                            },
                            openModule: (id, payload) => instance.visible && SpaceState.open(id, root.targetScreen, payload)
                        };
                        item.active = Qt.binding(() => instance.visible);
                        instance.deliverPending();
                        root.focusInitial();
                    }
                    // The Spaces' red loading ring, without depending on a Space.
                    BusySpinner {
                        anchors.centerIn: parent
                        width: 28
                        height: 28
                        foreground: "#e50914"
                        track: "#49313e"
                        visible: instance.status === Loader.Loading
                        running: visible && root.opened
                    }
                    ColumnLayout {
                        anchors.centerIn: parent
                        visible: instance.status === Loader.Error
                        ShellText {
                            text: qsTr("%1 could not be opened.").arg(instance.modelData.name)
                        }
                        ShellButton {
                            objectName: "closeFailedSpace:" + instance.modelData.id
                            text: qsTr("Close %1").arg(instance.modelData.name)
                            onClicked: SpaceState.close(instance.modelData.id)
                        }
                    }
                }
            }
        }
    }
}
