import QtQuick
import "../ui"

// Session controls belong on the left; their implementation remains deferred.
DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Provide direct access to Desktop and the spaces or modules that are available. Make the current destination clear, and let people return to Desktop without unexpectedly closing application windows. Spaces remains a static navigation button in the bar."),
                qsTr("Place session actions here on the left: lock, suspend, log out, restart and shut down, showing only the actions the system supports. Keep these distinct from navigation and label their effects clearly. The existing immediate Ctrl+Alt+Delete logout shortcut remains independent."),
                qsTr("Include temporary Stay awake and Keep screen on choices, with a clear indication of what is being held awake and how to return to normal behavior. Any temporary automatic-lock pause should be explicit and end with the session. Session controls and awake modes are still proposals, not working controls.")
            ].join("\n\n")
        }
    }
}
