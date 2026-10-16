pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQml.Models
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland

// Register metadata in the catalogue, then call toggleDrawer(key, screen) from
// any entry point. One native surface and one lazy page serve every category.
DrawerWindow {
    id: root

    property list<DrawerDefinition> definitions
    property DrawerDefinition currentDrawer: null
    readonly property DrawerPage currentPage: page.item as DrawerPage

    title: currentDrawer?.title ?? ""
    leftEdge: currentDrawer?.edge === DrawerDefinition.Left
    contentInitialFocus: currentPage?.initialFocus ?? null
    headerActions: currentPage?.headerActions ?? null
    escapeHandler: currentPage?.escapeHandler ?? null
    WlrLayershell.namespace: "desktop-drawer"

    function definition(key: string): DrawerDefinition {
        const matches = definitions.filter(entry => entry.key === key);
        if (!key || matches.length !== 1 || !matches[0].source.toString()
            || ![DrawerDefinition.Left, DrawerDefinition.Right].includes(matches[0].edge)) {
            console.warn("Unknown, duplicate or invalid drawer:", key);
            return null;
        }
        return matches[0];
    }

    function openDrawer(key: string, output: ShellScreen): void {
        // Invalid entry points must leave the current interaction untouched.
        if (!Quickshell.screens.includes(output))
            return;
        const entry = definition(key);
        if (!entry)
            return;
        if (currentDrawer !== entry || (presentationScreen && presentationScreen !== output)) {
            dismiss();
            resetPresentation();
            currentDrawer = entry;
        }
        openOn(output);
    }

    function toggleDrawer(key: string, output: ShellScreen): void {
        if (!Quickshell.screens.includes(output))
            return;
        const entry = definition(key);
        if (!entry)
            return;
        if (opened && currentDrawer === entry && interactionState.screen === output)
            dismiss();
        else
            openDrawer(key, output);
    }

    onDefinitionsChanged: if (currentDrawer && !definitions.includes(currentDrawer)) {
        dismiss();
        resetPresentation();
        currentDrawer = null;
    }

    Instantiator {
        model: root.definitions.filter(entry => entry.shortcut !== "")
        delegate: GlobalShortcut {
            required property DrawerDefinition modelData
            appid: "desktop"
            name: modelData.shortcut
            description: qsTr("Open or close %1").arg(modelData.title)
            onPressed: root.toggleDrawer(modelData.key, root.focusedOutput())
        }
    }

    Loader {
        id: page
        objectName: "drawerPageLoader"
        anchors.fill: parent
        active: root.opened || root.keepVisible
        asynchronous: true
        source: root.currentDrawer?.source ?? ""
        onLoaded: if (root.currentPage) {
            root.currentPage.screen = Qt.binding(() => root.targetScreen);
            root.currentPage.active = Qt.binding(() => root.opened);
            root.focusInitial();
        }
    }

    Connections {
        target: root.currentPage
        function onCloseRequested(): void { root.dismiss(); }
        function onDrawerRequested(key: string): void {
            root.openDrawer(key, root.interactionState.screen);
        }
    }

    BusySpinner {
        anchors.centerIn: parent
        visible: page.status === Loader.Loading
        running: visible && root.opened
    }

    ShellText {
        anchors.fill: parent
        visible: page.status === Loader.Error || (page.status === Loader.Ready && !root.currentPage)
        text: qsTr("This drawer could not be opened. Close it and try again.")
        wrapMode: Text.WordWrap
    }
}
