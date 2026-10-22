pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland

// Register metadata in the catalogue, then call toggleDrawer(key, screen) from
// any entry point. One native surface and one lazy page serve every category.
InteractionWindow {
    id: root

    property list<DrawerDefinition> definitions
    readonly property var drawersByKey: {
        const map = {};
        for (const entry of definitions)
            map[entry.key] = entry;
        return map;
    }
    property DrawerDefinition currentDrawer: null
    readonly property DrawerPage currentPage: page.item as DrawerPage
    readonly property bool leftEdge: currentDrawer?.edge === DrawerDefinition.Left
    property real slideProgress: 0
    // The drawer keeps its presentation while the exit animation runs; input
    // ownership still follows opened, so a closing drawer cannot take input.
    // Keep this true while open too: opened/keepVisible must not both become
    // false during handoff to closing, which would destroy/recreate lazy content.
    readonly property bool keepVisible: slideProgress > 0
        && (interactionState.activeSurface === null || interactionState.activeSurface === root)
        && Quickshell.screens.includes(presentationScreen)
    property ShellScreen presentationScreen: null

    targetScreen: opened ? interactionState.screen : keepVisible ? presentationScreen : null
    visible: (opened || keepVisible) && targetScreen !== null
    initialFocus: currentPage?.initialFocus ?? closeButton
    escapeHandler: currentPage?.escapeHandler ?? null
    backdropOpacity: slideProgress
    WlrLayershell.namespace: "desktop-drawer"

    function definition(key: string): DrawerDefinition {
        const entry = Object.prototype.hasOwnProperty.call(drawersByKey, key) ? drawersByKey[key] : null;
        if (!entry)
            console.warn("Unknown drawer:", key);
        return entry;
    }

    function resetPresentation(): void {
        slide.stop();
        slideProgress = 0;
        presentationScreen = null;
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
        if (opened && currentDrawer?.key === key && interactionState.screen === output)
            dismiss();
        else
            openDrawer(key, output);
    }

    onOpenedChanged: {
        if (opened)
            presentationScreen = interactionState.screen;
        slide.to = opened ? 1 : 0;
        slide.restart();
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

    NumberAnimation {
        id: slide
        target: root
        property: "slideProgress"
        duration: 200
        easing.type: Easing.OutCubic
        onFinished: if (!root.opened) root.presentationScreen = null
    }

    Connections {
        target: root.interactionState
        function onActiveSurfaceChanged(): void {
            // A replacement opens immediately. Drop the old presentation so
            // two drawers/scrims cannot overlap or briefly obscure the new one.
            if (root.interactionState.activeSurface && root.interactionState.activeSurface !== root)
                root.resetPresentation();
        }
    }

    Connections {
        target: Quickshell
        function onScreensChanged(): void {
            if (!Quickshell.screens.includes(root.presentationScreen))
                root.resetPresentation();
        }
    }

    Connections {
        target: root.currentPage
        function onCloseRequested(): void { root.dismiss(); }
    }

    Surface {
        id: card
        objectName: "drawerCard"
        x: root.leftEdge ? -width * (1 - root.slideProgress)
            : root.width - width * root.slideProgress
        width: Math.min(Theme.drawerWidth, root.width)
        height: root.height
        radius: 0
        color: Theme.background
        enabled: root.opened

        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.padding
            spacing: Theme.padding

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap
                ShellText {
                    objectName: "drawerTitleBlock"
                    text: root.currentDrawer?.title ?? ""
                    font.pixelSize: Theme.titleFontSize
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    elide: Text.ElideRight
                }
                Loader {
                    objectName: "drawerHeaderActions"
                    active: !!root.currentPage?.headerActions
                    visible: active
                    sourceComponent: root.currentPage?.headerActions ?? null
                    Layout.alignment: Qt.AlignVCenter
                }
                Button {
                    id: closeButton
                    objectName: "drawerClose"
                    text: qsTr("Close %1").arg(root.currentDrawer?.title ?? "")
                    Layout.preferredWidth: Theme.controlHeight
                    Layout.preferredHeight: Theme.controlHeight
                    padding: (Theme.controlHeight - Theme.iconSize) / 2
                    hoverEnabled: true
                    onClicked: root.dismiss()
                    contentItem: Icon {
                        name: "x"
                        color: closeButton.down ? Theme.muted
                            : closeButton.hovered || closeButton.visualFocus ? Theme.accent : Theme.text
                    }
                    background: Rectangle {
                        color: "transparent"
                        radius: Theme.controlRadius
                        // Ghost buttons keep keyboard focus visible without a fill.
                        border.width: closeButton.visualFocus ? 1 : 0
                        border.color: Theme.accent
                    }
                    PassiveToolTip { target: closeButton }
                }
            }

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

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
        }
    }
}
