pragma ComponentBehavior: Bound
import QtQuick
import Quickshell.Hyprland
import "../ui"

Surface {
    id: root
    objectName: "workspaceList"

    required property HyprlandMonitor monitor
    // Window addresses still needing attention, tracked by the bar.
    required property var attention
    property real maximumWidth: Theme.controlHeight
    readonly property HyprlandWorkspace current: monitor?.activeWorkspace ?? null
    readonly property var workspaces: Hyprland.workspaces.values.filter(workspace => workspace && workspace.monitor === root.monitor && workspace.id > 0).sort((a, b) => a.id - b.id)
    readonly property int currentIndex: workspaces.indexOf(current)
    readonly property bool occupied: !!current && current.toplevels.values.length > 0
    readonly property var urgentIds: Hyprland.toplevels.values.filter(window => attention.includes(window.address) && window.workspace?.monitor === root.monitor).map(window => window.workspace.id)
    readonly property bool urgentAbove: !!current && urgentIds.some(id => id > 0 && id < current.id)
    readonly property bool urgentBelow: !!current && urgentIds.some(id => id > current.id)
    readonly property bool canGoUp: Hyprland.usingLua && currentIndex >= 0 && (currentIndex > 0 || (occupied && current.id > 1))
    readonly property bool canGoDown: Hyprland.usingLua && currentIndex >= 0 && (currentIndex < workspaces.length - 1 || (occupied && current.id < 2147483646))

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
        objectName: "workspaceUp"
        width: root.width
        height: root.height / 2
        padding: 0
        text: urgent ? qsTr("Window above needs attention (Ctrl+Win+Up)") : qsTr("Workspace above (Ctrl+Win+Up)")
        urgent: root.urgentAbove
        enabled: root.canGoUp
        onClicked: root.step(-1)
        PassiveToolTip {
            target: up
        }
        contentItem: Item {
            Icon {
                anchors.centerIn: parent
                width: 16
                height: 16
                name: "chevron-up"
                color: up.urgent ? Theme.warning : Theme.text
                opacity: up.enabled ? 1 : 0.35
            }
        }
    }

    BarButton {
        id: down
        objectName: "workspaceDown"
        y: root.height / 2
        width: root.width
        height: root.height / 2
        padding: 0
        text: urgent ? qsTr("Window below needs attention (Ctrl+Win+Down)") : qsTr("Workspace below (Ctrl+Win+Down)")
        urgent: root.urgentBelow
        enabled: root.canGoDown
        onClicked: root.step(1)
        PassiveToolTip {
            target: down
        }
        contentItem: Item {
            Icon {
                anchors.centerIn: parent
                width: 16
                height: 16
                name: "chevron-down"
                color: down.urgent ? Theme.warning : Theme.text
                opacity: down.enabled ? 1 : 0.35
            }
        }
    }
}
