pragma ComponentBehavior: Bound
import QtQuick
import Quickshell.Hyprland
import "../ui"

Surface {
    id: root

    required property HyprlandMonitor monitor
    property real maximumWidth: Theme.controlHeight
    readonly property HyprlandWorkspace current: monitor?.activeWorkspace ?? null
    readonly property var workspaces: Hyprland.workspaces.values
        .filter(workspace => workspace && workspace.monitor === root.monitor && workspace.id > 0)
        .sort((a, b) => a.id - b.id)
    readonly property int currentIndex: workspaces.indexOf(current)
    readonly property bool occupied: !!current && current.toplevels.values.length > 0
    readonly property bool canGoUp: Hyprland.usingLua && currentIndex >= 0
        && (currentIndex > 0 || (occupied && current.id > 1))
    readonly property bool canGoDown: Hyprland.usingLua && currentIndex >= 0
        && (currentIndex < workspaces.length - 1 || (occupied && current.id < 2147483646))

    function step(direction: int): void {
        if (!monitor || (direction < 0 ? !canGoUp : !canGoDown))
            return;
        // Recheck against live compositor state; queued clicks cannot grow a
        // chain of empties even before Quickshell receives the workspace event.
        Hyprland.dispatch("function() DesktopWorkspaces.step(" + direction + ", " + monitor.id + ") end");
    }

    implicitWidth: Math.min(Math.max(0, maximumWidth), Theme.controlHeight)
    implicitHeight: Theme.controlHeight
    radius: Theme.controlRadius
    border.width: 0
    clip: true
    visible: !!monitor && width > 0

    BarButton {
        id: up
        width: root.width
        height: root.height / 2
        padding: 0
        text: qsTr("Workspace above (Ctrl+Win+Up)")
        enabled: root.canGoUp
        onClicked: root.step(-1)
        contentItem: Item {
            Icon {
                anchors.centerIn: parent
                width: 16
                height: 16
                name: "chevron-up"
                opacity: up.enabled ? 1 : 0.35
            }
        }
    }

    BarButton {
        id: down
        y: root.height / 2
        width: root.width
        height: root.height / 2
        padding: 0
        text: qsTr("Workspace below (Ctrl+Win+Down)")
        enabled: root.canGoDown
        onClicked: root.step(1)
        contentItem: Item {
            Icon {
                anchors.centerIn: parent
                width: 16
                height: 16
                name: "chevron-down"
                opacity: down.enabled ? 1 : 0.35
            }
        }
    }
}
