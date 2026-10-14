import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Show recent copied text and images in a searchable history. Each entry should have an appropriate preview, with a way to inspect longer text or a larger image before choosing it. Selecting an entry copies it back to the clipboard and returns focus to the application."),
                qsTr("Offer removal of individual entries, clear history, and pause history collection. Make retention limits and any persistence choice explicit, and provide a practical way to avoid retaining sensitive content. Keep clipboard contents out of bar labels."),
                qsTr("Distinguish an empty history from paused collection or an unavailable clipboard service. Direct pasting or simulated typing should be a separate, deliberate action rather than a side effect of selecting an entry.")
            ].join("\n\n")
        }
    }
}
