pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Hyprland
import "../ui"

Surface {
    id: root

    required property HyprlandMonitor monitor
    property real maximumWidth: 320
    readonly property var workspaces: Hyprland.workspaces.values.filter(workspace => workspace && workspace.monitor === root.monitor
        && !workspace.name.startsWith("special:"))

    function cellWidth(workspace: HyprlandWorkspace): real {
        return Math.max(Theme.controlHeight, Math.min(120,
            Math.ceil(metrics.advanceWidth(workspace?.name ?? "")) + Theme.padding));
    }

    implicitWidth: Math.min(Math.max(0, maximumWidth), workspaces.reduce((width, workspace) => width + cellWidth(workspace), 0)
        + Math.max(0, workspaces.length - 1) * Theme.spacingSmall + Theme.spacingSmall * 2)
    implicitHeight: Theme.controlHeight
    radius: Theme.pillRadius
    border.width: 0
    visible: workspaces.length > 0 && width > 0

    FontMetrics {
        id: metrics
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize
    }

    ListView {
        id: list
        anchors.fill: parent
        anchors.leftMargin: Theme.spacingSmall
        anchors.rightMargin: Theme.spacingSmall
        clip: true
        orientation: ListView.Horizontal
        boundsBehavior: Flickable.StopAtBounds
        spacing: Theme.spacingSmall
        model: ScriptModel { values: root.workspaces }

        delegate: BarButton {
            required property HyprlandWorkspace modelData
            text: modelData?.name ?? ""
            width: root.cellWidth(modelData)
            height: Theme.controlHeight
            selected: modelData?.active ?? false
            urgent: modelData?.urgent ?? false
            enabled: !!modelData
            onClicked: if (modelData) modelData.activate()
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.NoButton
            onWheel: event => {
                const pixels = event.pixelDelta.x || event.pixelDelta.y;
                const angle = event.angleDelta.x || event.angleDelta.y;
                const delta = pixels || angle / 120 * Theme.controlHeight;
                list.contentX = Math.max(0, Math.min(Math.max(0, list.contentWidth - list.width), list.contentX - delta));
                event.accepted = true;
            }
        }
    }
}
