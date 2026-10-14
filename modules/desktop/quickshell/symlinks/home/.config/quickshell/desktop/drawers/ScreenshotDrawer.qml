import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Offer region, window and whole-display capture, with a clear choice between editing the result and saving or copying it directly. Show the destination and the relevant existing screenshot shortcuts."),
                qsTr("Keep capture selection out of the way of the drawer itself. Cancelling selection should return to the desktop without creating a file or replacing the clipboard. After a successful capture, make the saved image or its folder easy to open."),
                qsTr("Reuse the established capture and editing workflow. Screen recording has its own drawer; this drawer should stay focused on still images and explain failures without losing the chosen capture options.")
            ].join("\n\n")
        }
    }
}
