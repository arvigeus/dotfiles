import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Combine a calendar and selected-day agenda with notification history. Make today and the selected day clear, and show scheduled events with useful times and source information when a calendar source has been configured. Distinguish no events from an unavailable or unconfigured source."),
                qsTr("Show notification sender, time, content and supported actions, with individual dismissal and a deliberate clear-history action. Define what read, unread and dismissed mean so the bar badge has a predictable meaning. Keep event indicators distinct from unseen-notification counts."),
                qsTr("Include quiet or Do Not Disturb controls with a visible state and an optional duration. Suppressing popups should not silently discard notification history. Calendar accounts, event editing and remote integrations remain separate follow-up proposals; local date navigation and notification handling can be implemented first.")
            ].join("\n\n")
        }
    }
}
