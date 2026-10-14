import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Show useful storage capacity and free-space summaries for mounted volumes, with clear names, mount locations and removable-drive status. Provide direct access to each location in the file manager."),
                qsTr("Offer supported mount, unlock, unmount and safe-eject actions, explaining busy devices or failed operations in context. Make it clear which physical device or volume an action affects."),
                qsTr("Detailed health information should be available on request where supported, without ordinary status updates waking sleeping disks. Deeper partitioning, formatting and repair should open an appropriate storage tool instead of becoming quick actions in this drawer.")
            ].join("\n\n")
        }
    }
}
