pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell

InteractionWindow {
    id: root
    objectName: "spaceHost"
    property var pendingPayloads: ({})
    readonly property var currentEntry: SpaceState.entries.find(entry => entry.id === SpaceState.currentId)
    readonly property var currentPage: {
        for (let i = 0; i < instances.count; ++i) {
            const loader = instances.itemAt(i);
            if (loader?.modelData.id === SpaceState.currentId)
                return loader.item;
        }
        return null;
    }
    initialFocus: currentPage?.initialFocus ?? hideButton
    escapeHandler: () => {
        if (!root.currentPage?.dismissTransient())
            root.dismiss();
    }
    Component.onCompleted: SpaceState.host = root
    Component.onDestruction: if (SpaceState.host === root)
        SpaceState.host = null

    function deliver(id, payload) {
        if (!payload)
            return;
        pendingPayloads[id] = payload;
        for (let i = 0; i < instances.count; ++i) {
            const loader = instances.itemAt(i);
            if (loader?.modelData.id === id && loader.item)
                deliverPending(loader);
        }
    }
    function deliverPending(loader) {
        const payload = pendingPayloads[loader.modelData.id];
        delete pendingPayloads[loader.modelData.id];
        if (payload && loader.item.handleOpen)
            loader.item.handleOpen(payload);
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
                    anchors.fill: parent
                    active: SpaceState.runningIds.includes(modelData.id)
                    visible: root.opened && SpaceState.currentId === modelData.id
                    asynchronous: true
                    source: Qt.resolvedUrl(modelData.source)
                    onLoaded: {
                        const owner = modelData.id;
                        if ("backdropTarget" in item)
                            item.backdropTarget = backdropLayer;
                        if ("toolbarTarget" in item)
                            item.toolbarTarget = toolbarLayer;
                        item.host = {
                            hide: () => {
                                if (SpaceState.currentId === owner)
                                    SpaceState.hide();
                            },
                            close: () => SpaceState.close(owner),
                            openModule: (id, payload) => SpaceState.open(id, root.targetScreen, payload)
                        };
                        item.active = Qt.binding(() => instance.visible);
                        root.deliverPending(instance);
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
                            text: qsTr("Close %1").arg(instance.modelData.name)
                            onClicked: SpaceState.close(instance.modelData.id)
                        }
                    }
                }
            }
        }
    }
}
