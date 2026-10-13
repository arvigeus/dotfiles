pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQml.Models
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import "../ui"

Surface {
    id: root

    required property HyprlandMonitor monitor
    property real maximumWidth: 640
    readonly property int cellWidth: 160
    readonly property var applicationEntries: DesktopEntries.applications.values
    // Hyprland supplies placement; each window's Wayland handle supplies live metadata.
    readonly property var windowCandidates: Hyprland.toplevels.values
        .filter(toplevel => toplevel && toplevel.monitor === root.monitor
            && toplevel.workspace && toplevel.workspace === root.monitor?.activeWorkspace)
    readonly property var windows: orderedWindows
    property var orderedWindows: []

    onWindowCandidatesChanged: Qt.callLater(root.updateWindowOrder)
    Component.onCompleted: Qt.callLater(root.updateWindowOrder)

    // A native refresh updates clients individually. Publish once after the batch
    // so scrolling all columns cannot briefly mix old and new coordinates.
    Instantiator {
        model: root.windowCandidates
        delegate: Connections {
            required property HyprlandToplevel modelData
            target: modelData
            function onLastIpcObjectChanged() { Qt.callLater(root.updateWindowOrder); }
        }
    }

    function updateWindowOrder(): void {
        const next = windowCandidates.filter(window => window && window.workspace)
            .map(window => {
                const position = window.lastIpcObject.at;
                return {
                    window: window,
                    x: position?.[0] ?? Number.MAX_SAFE_INTEGER,
                    y: position?.[1] ?? Number.MAX_SAFE_INTEGER,
                    address: window.address
                };
            })
            // Read columns left-to-right and stacks top-to-bottom on this workspace.
            // Break overlaps consistently.
            .sort((a, b) => a.x - b.x || a.y - b.y
                || a.address.localeCompare(b.address))
            .map(entry => entry.window);

        if (next.length !== orderedWindows.length
            || next.some((window, index) => window !== orderedWindows[index]))
            orderedWindows = next;
    }

    function activate(toplevel: HyprlandToplevel): void {
        if (!toplevel || !Hyprland.toplevels.values.includes(toplevel) || !Hyprland.usingLua)
            return;
        if (!/^(0x)?[0-9a-f]+$/i.test(toplevel.address))
            return;
        const address = toplevel.address.replace(/^0x/i, "");
        Hyprland.dispatch('hl.dsp.focus({window = "address:0x' + address + '"})');
    }

    implicitWidth: Math.min(Math.max(0, maximumWidth),
        windows.length * cellWidth + Math.max(0, windows.length - 1) * Theme.spacingSmall)
    implicitHeight: Theme.controlHeight
    // Match the full-height item backgrounds so hovering an end keeps its shape.
    radius: Theme.controlRadius
    border.width: 0
    visible: windows.length > 0 && width > 0

    ListView {
        id: list
        anchors.fill: parent
        clip: true
        orientation: ListView.Horizontal
        boundsBehavior: Flickable.StopAtBounds
        spacing: Theme.spacingSmall
        model: ScriptModel { values: root.windows }

        delegate: BarButton {
            id: button
            required property HyprlandToplevel modelData
            readonly property Toplevel wayland: modelData ? modelData.wayland : null
            readonly property string appId: wayland && wayland.appId ? wayland.appId
                : (modelData ? modelData.lastIpcObject.class || "" : "")
            readonly property var desktopEntry: root.applicationEntries.length
                ? DesktopEntries.heuristicLookup(appId) : null

            width: root.cellWidth
            height: Theme.controlHeight
            text: (wayland ? wayland.title : modelData?.title) || appId || "Untitled window"
            selected: wayland ? wayland.activated : (modelData?.activated ?? false)
            urgent: modelData?.urgent ?? false
            enabled: Hyprland.usingLua && !!modelData && modelData.address.length > 0
            onClicked: root.activate(modelData)

            contentItem: RowLayout {
                spacing: Theme.spacingMedium
                AppIcon {
                    icon: button.desktopEntry ? button.desktopEntry.icon : button.appId
                    Layout.preferredWidth: Theme.iconSize
                    Layout.preferredHeight: Theme.iconSize
                }
                ShellText {
                    text: button.text
                    color: button.urgent ? Theme.danger : Theme.text
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                BarButton {
                    id: closeButton
                    Layout.preferredWidth: Theme.iconSize + Theme.spacingSmall
                    Layout.preferredHeight: Theme.iconSize + Theme.spacingSmall
                    padding: Theme.spacingSmall
                    text: qsTr("Close %1").arg(button.text)
                    enabled: !!button.wayland
                    // The child button consumes its click; closing needs no activation.
                    onClicked: if (button.wayland) button.wayland.close()

                    contentItem: Icon {
                        name: "x"
                        color: closeButton.hovered || closeButton.down ? Theme.danger : Theme.muted
                    }
                }
            }
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.NoButton
            onWheel: event => {
                const pixels = event.pixelDelta.x || event.pixelDelta.y;
                const angle = event.angleDelta.x || event.angleDelta.y;
                const delta = pixels || angle / 120 * root.cellWidth;
                list.contentX = Math.max(0, Math.min(Math.max(0, list.contentWidth - list.width), list.contentX - delta));
                event.accepted = true;
            }
        }
    }
}
