pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import "../ui"

Surface {
    id: root
    objectName: "windowList"

    required property HyprlandMonitor monitor
    // Window addresses still needing attention, tracked by the bar.
    required property var attention
    property real maximumWidth: 640
    readonly property int cellWidth: 160
    // Crowded strips shrink tabs to this width before scrolling. A strip too
    // narrow for one such tab shows a single tab at its own width.
    readonly property int minimumCellWidth: 96
    readonly property real available: Math.max(0, maximumWidth)
    readonly property int tabWidth: windows.length ? Math.floor(Math.min(cellWidth, Math.max(Math.min(minimumCellWidth, available), (available - (windows.length - 1) * Theme.spacingSmall) / windows.length))) : cellWidth
    readonly property real stride: tabWidth + Theme.spacingSmall
    readonly property var applicationEntries: DesktopEntries.applications.values
    // Hyprland supplies placement; each window's Wayland handle supplies live metadata.
    readonly property var windowCandidates: Hyprland.toplevels.values.filter(toplevel => toplevel && toplevel.monitor === root.monitor && toplevel.workspace && toplevel.workspace === root.monitor?.activeWorkspace)
    // A native refresh updates clients individually. Publish once after the batch
    // so scrolling all columns cannot briefly mix old and new coordinates.
    readonly property var placement: windowCandidates.map(window => window.lastIpcObject.at)
    property var windows: []
    readonly property int activeIndex: windows.findIndex(window => window.wayland ? window.wayland.activated : window.activated)

    // Tabs not wholly in view on each side, counted by the edge markers.
    readonly property bool showEdges: width >= minimumCellWidth * 2
    readonly property int hiddenBefore: list.atXBeginning ? 0 : Math.max(1, Math.ceil((list.contentX - list.originX - 0.5) / stride))
    readonly property int hiddenAfter: list.atXEnd ? 0 : Math.max(1, Math.min(windows.length, windows.length - 1 - Math.floor((list.contentX - list.originX + list.width - tabWidth + 0.5) / stride)))
    readonly property bool urgentBefore: windows.slice(0, hiddenBefore).some(window => attention.includes(window.address))
    readonly property bool urgentAfter: windows.slice(windows.length - hiddenAfter).some(window => attention.includes(window.address))

    onPlacementChanged: Qt.callLater(root.updateWindowOrder)
    Component.onCompleted: Qt.callLater(root.updateWindowOrder)
    // Like the compositor's view, the strip follows keyboard focus.
    onActiveIndexChanged: Qt.callLater(root.revealActive)

    function revealActive(): void {
        reveal(activeIndex);
    }

    // Scroll the least distance that shows a tab clear of the edge markers.
    function reveal(index: int): void {
        if (index < 0 || index >= windows.length)
            return;
        list.positionViewAtIndex(index, ListView.Contain);
        const item = list.itemAtIndex(index);
        if (!item || !showEdges)
            return;
        if (index > 0 && item.x - list.contentX < before.width)
            wheel.scrollTo(item.x - before.width);
        else if (index < windows.length - 1 && item.x + item.width - list.contentX > list.width - after.width)
            wheel.scrollTo(item.x + item.width + after.width - list.width);
    }

    // Jump to the nearest hidden window needing attention, else scroll a page.
    function page(direction: int): void {
        const hidden = windows.map((_, index) => index).filter(index => direction < 0 ? index < hiddenBefore : index >= windows.length - hiddenAfter);
        const urgent = (direction < 0 ? hidden.reverse() : hidden).find(index => attention.includes(windows[index].address));
        if (urgent !== undefined)
            reveal(urgent);
        else
            wheel.scrollTo(list.contentX + direction * Math.max(stride, list.width - stride));
    }

    function updateWindowOrder(): void {
        const next = windowCandidates.filter(window => window && window.workspace).map(window => {
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
        .sort((a, b) => a.x - b.x || a.y - b.y || a.address.localeCompare(b.address)).map(entry => entry.window);

        if (next.length !== windows.length || next.some((window, index) => window !== windows[index]))
            windows = next;
    }

    function activate(toplevel: HyprlandToplevel): void {
        if (!toplevel || !Hyprland.toplevels.values.includes(toplevel) || !Hyprland.usingLua)
            return;
        if (!/^(0x)?[0-9a-f]+$/i.test(toplevel.address))
            return;
        const address = toplevel.address.replace(/^0x/i, "");
        Hyprland.dispatch('hl.dsp.focus({window = "address:0x' + address + '"})');
    }

    implicitWidth: Math.min(available, windows.length * tabWidth + Math.max(0, windows.length - 1) * Theme.spacingSmall)
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
        model: ScriptModel {
            values: root.windows
        }

        delegate: BarButton {
            id: button
            required property HyprlandToplevel modelData
            readonly property Toplevel wayland: modelData ? modelData.wayland : null
            readonly property string appId: wayland && wayland.appId ? wayland.appId : (modelData ? modelData.lastIpcObject.class || "" : "")
            readonly property var desktopEntry: root.applicationEntries.length ? DesktopEntries.heuristicLookup(appId) : null

            objectName: "window:" + (modelData?.address ?? "")
            width: root.tabWidth
            height: Theme.controlHeight
            text: (wayland ? wayland.title : modelData?.title) || appId || "Untitled window"
            selected: wayland ? wayland.activated : (modelData?.activated ?? false)
            urgent: !!modelData && root.attention.includes(modelData.address)
            enabled: Hyprland.usingLua && !!modelData && modelData.address.length > 0
            onClicked: root.activate(modelData)
            PassiveToolTip {
                target: button
                text: button.urgent ? qsTr("%1 — needs attention").arg(button.text) : button.text
            }
            // Spans the whole tab, so showing the close button keeps it hovered.
            HoverHandler {
                id: tabHover
            }

            contentItem: RowLayout {
                spacing: Theme.spacingMedium
                AppIcon {
                    icon: button.desktopEntry ? button.desktopEntry.icon : button.appId
                    Layout.preferredWidth: Theme.iconSize
                    Layout.preferredHeight: Theme.iconSize
                }
                Rectangle {
                    visible: button.urgent
                    Layout.preferredWidth: 6
                    Layout.preferredHeight: 6
                    radius: 3
                    color: Theme.warning
                }
                ShellText {
                    text: button.text
                    color: button.urgent ? Theme.warning : Theme.text
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                BarButton {
                    id: closeButton
                    objectName: "closeWindow"
                    // Shrunk tabs give the title this space until hovered.
                    visible: button.width >= root.cellWidth || tabHover.hovered
                    Layout.preferredWidth: Theme.iconSize + Theme.spacingSmall
                    Layout.preferredHeight: Theme.iconSize + Theme.spacingSmall
                    padding: Theme.spacingSmall
                    text: qsTr("Close %1").arg(button.text)
                    enabled: !!button.wayland
                    // The child button consumes its click; closing needs no activation.
                    onClicked: if (button.wayland)
                        button.wayland.close()

                    contentItem: Icon {
                        name: "x"
                        color: closeButton.hovered || closeButton.down ? Theme.danger : Theme.muted
                    }
                }
            }
        }

        WheelScroll {
            id: wheel
            view: list
            orientation: Qt.Horizontal
            verticalToHorizontal: true
            wheelStep: root.stride
            scrollGestureEnabled: true
        }
    }

    // Opaque over the tabs it hides, fading toward the visible ones; amber like
    // the workspace arrows when a hidden window needs attention. Its width
    // includes the fade, so revealed tabs stay clear of both.
    component EdgeMarker: Item {
        id: edge
        required property int direction
        required property int hidden
        required property bool urgent

        visible: root.showEdges && hidden > 0
        width: marker.implicitWidth + Theme.gap
        height: root.height

        Rectangle {
            x: edge.direction < 0 ? marker.implicitWidth : 0
            width: Theme.gap
            height: parent.height
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop {
                    position: edge.direction < 0 ? 0 : 1
                    color: root.color
                }
                GradientStop {
                    position: edge.direction < 0 ? 1 : 0
                    color: Qt.rgba(root.color.r, root.color.g, root.color.b, 0)
                }
            }
        }

        Rectangle {
            x: edge.direction < 0 ? 0 : Theme.gap
            width: marker.implicitWidth
            height: parent.height
            color: root.color
            radius: root.radius

            BarButton {
                id: marker
                anchors.fill: parent
                implicitWidth: contentItem.implicitWidth + leftPadding + rightPadding
                padding: Theme.spacingSmall
                urgent: edge.urgent
                text: (edge.direction < 0 ? (edge.hidden === 1 ? qsTr("1 more window to the left") : qsTr("%1 more windows to the left").arg(edge.hidden)) : (edge.hidden === 1 ? qsTr("1 more window to the right") : qsTr("%1 more windows to the right").arg(edge.hidden))) + (edge.urgent ? " · " + qsTr("needs attention") : "")
                onClicked: root.page(edge.direction)
                PassiveToolTip {
                    target: marker
                }
                contentItem: Row {
                    spacing: 2
                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 16
                        height: 16
                        name: edge.direction < 0 ? "chevron-left" : "chevron-right"
                        color: edge.urgent ? Theme.warning : Theme.text
                    }
                    ShellText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: String(edge.hidden)
                        font.pixelSize: Theme.smallFontSize
                        color: edge.urgent ? Theme.warning : Theme.muted
                    }
                }
            }
        }
    }

    EdgeMarker {
        id: before
        objectName: "windowsBefore"
        direction: -1
        hidden: root.hiddenBefore
        urgent: root.urgentBefore
    }
    EdgeMarker {
        id: after
        objectName: "windowsAfter"
        anchors.right: parent.right
        direction: 1
        hidden: root.hiddenAfter
        urgent: root.urgentAfter
    }
}
