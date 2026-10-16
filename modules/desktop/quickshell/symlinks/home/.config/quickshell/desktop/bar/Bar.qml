import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import "../ui"

PanelWindow {
    id: bar

    signal launcherRequested()
    signal drawerRequested(string key)

    anchors { top: true; left: true; right: true }
    implicitHeight: Theme.pillHeight
    exclusiveZone: Theme.pillHeight
    color: "transparent"
    readonly property HyprlandMonitor monitor: Hyprland.monitorFor(screen)

    // Keep the reservation mapped while fullscreen windows cover the Top layer.
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.namespace: "desktop-bar"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    mask: Region {
        Region { item: spacesButton.visible ? spacesButton : null; radius: Theme.pillRadius }
        Region { item: workspaces.visible ? workspaces : null; radius: workspaces.radius }
        Region { item: windows.visible ? windows : null; radius: windows.radius }
        Region { item: launcherButton.visible ? launcherButton : null; radius: Theme.controlRadius }
        Region {
            Region { item: status.trayIsland; radius: Theme.pillRadius }
            Region { item: status.toolsIsland; radius: Theme.pillRadius }
            Region { item: status.systemIsland; radius: Theme.pillRadius }
            Region { item: status.notificationsIsland; radius: Theme.pillRadius }
            // Intersect after combining: offscreen controls cannot steal input
            // from the window strip; gaps between the islands stay transparent.
            Region { item: status; intersection: Intersection.Intersect }
        }
    }

    BarButton {
        id: spacesButton
        objectName: "spacesButton"
        x: Theme.barInset
        y: Theme.pillTopPadding
        width: Math.min(contentItem.implicitWidth + Theme.gap * 2,
            Math.max(0, bar.width - Theme.barInset * 2 - Theme.controlHeight - Theme.spacingMedium))
        height: Theme.controlHeight
        padding: 0
        leftPadding: Theme.gap
        rightPadding: Theme.gap
        visible: width > 0
        clip: true
        text: qsTr("Spaces")
        onClicked: bar.drawerRequested("spaces")
        contentItem: RowLayout {
            spacing: Theme.spacingMedium
            Icon {
                name: "list"
                Layout.preferredWidth: Theme.iconSize
                Layout.preferredHeight: Theme.iconSize
                Layout.alignment: Qt.AlignVCenter
            }
            ShellText {
                text: spacesButton.text
                Layout.fillHeight: true
                verticalAlignment: Text.AlignVCenter
            }
        }
        background: ButtonBackground {
            radius: Theme.pillRadius
            pressed: spacesButton.down
            idleColor: spacesButton.hovered ? Theme.raised : Theme.surface
        }
    }

    WorkspaceList {
        id: workspaces
        monitor: bar.monitor
        x: spacesButton.x + spacesButton.width + Theme.spacingMedium
        y: Theme.pillTopPadding
        maximumWidth: Math.max(0, status.x - x
            - launcherButton.width - Theme.spacingMedium * 2)
    }

    WindowList {
        id: windows
        monitor: bar.monitor
        x: workspaces.x + (workspaces.visible ? workspaces.width + Theme.spacingMedium : 0)
        y: Theme.pillTopPadding
        maximumWidth: Math.max(0, status.x - x
            - launcherButton.width - Theme.spacingMedium * 2)
    }

    StatusIslands {
        id: status
        outputName: bar.screen?.name ?? ""
        x: bar.width - Theme.barInset - width
        y: Theme.pillTopPadding
        // Reserve Spaces, workspace navigation, launcher and a minimum window
        // slot. Narrow outputs scroll the islands rather than lose destinations.
        maximumWidth: Math.max(0, bar.width - Theme.barInset * 2 - spacesButton.width
            - Theme.controlHeight * 3 - Theme.spacingMedium * 5)
        onDrawerRequested: key => bar.drawerRequested(key)
    }

    BarButton {
        id: launcherButton
        objectName: "applicationLauncherButton"
        x: windows.x + (windows.visible ? windows.width + Theme.spacingMedium : 0)
        y: Theme.pillTopPadding
        width: Math.min(Theme.controlHeight, Math.max(0, bar.width - Theme.barInset * 2))
        height: Theme.controlHeight
        visible: width > 0
        padding: (Theme.controlHeight - Theme.iconSize) / 2
        text: qsTr("Open application")
        PassiveToolTip { target: launcherButton }
        onClicked: bar.launcherRequested()
        contentItem: Icon { name: "plus" }
        background: ButtonBackground {
            pressed: launcherButton.down
            idleColor: launcherButton.hovered ? Theme.raised : Theme.surface
        }
    }

}
