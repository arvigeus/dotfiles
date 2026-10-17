import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Recording backend: wf-recorder. Support region and whole-display capture; region capture records a fixed rectangle."),
                qsTr("Provide recording controls with system-audio and microphone choices supported by the recording tool. Show where recordings are saved and make the current recording state, elapsed time and Stop action easy to find."),
                qsTr("Keep source selection and permissions with the existing recording workflow. Closing this drawer should not stop a recording that has already started. The bar should visibly indicate an active recording and provide a quick route back to its controls."),
                qsTr("After recording, offer access to the saved file and destination folder. Keep unavailable audio sources, cancellation and recording failures distinct; screenshot capture remains a separate destination.")
            ].join("\n\n")
        }
    }
}
