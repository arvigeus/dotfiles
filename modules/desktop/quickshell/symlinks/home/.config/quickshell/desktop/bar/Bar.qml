import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import "../ui"

PanelWindow {
    id: bar

    signal launcherRequested()

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
        Region { item: workspaces.visible ? workspaces : null; radius: workspaces.radius }
        Region { item: windows.visible ? windows : null; radius: windows.radius }
        Region { item: launcherButton.visible ? launcherButton : null; radius: Theme.controlRadius }
    }

    WorkspaceList {
        id: workspaces
        monitor: bar.monitor
        x: Theme.barInset
        y: Theme.pillTopPadding
        maximumWidth: Math.max(0, bar.width - Theme.barInset * 2
            - launcherButton.width - Theme.spacingMedium)
    }

    WindowList {
        id: windows
        monitor: bar.monitor
        x: workspaces.x + (workspaces.visible ? workspaces.width + Theme.spacingMedium : 0)
        y: Theme.pillTopPadding
        maximumWidth: Math.max(0, bar.width - x - Theme.barInset
            - launcherButton.width - Theme.spacingMedium)
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
