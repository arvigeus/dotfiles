pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell

InteractionWindow {
    id: root
    objectName: "spaceHost"
    readonly property var currentEntry: SpaceState.entries.find(entry => entry.id === SpaceState.currentId)
    readonly property var currentPage: instanceFor(SpaceState.currentId)?.item ?? null
    initialFocus: currentPage?.initialFocus ?? hideButton
    escapeHandler: () => {
        if (!root.currentPage?.dismissTransient())
            root.dismiss();
    }
    Component.onCompleted: SpaceState.host = root
    Component.onDestruction: if (SpaceState.host === root)
        SpaceState.host = null

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
