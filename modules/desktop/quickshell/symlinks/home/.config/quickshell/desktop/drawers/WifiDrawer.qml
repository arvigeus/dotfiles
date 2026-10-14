import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Start with Wi-Fi enabled state, the connected network, signal strength and connection status. List saved and nearby networks with their security and connection state, and support connecting, disconnecting and forgetting a saved network."),
                qsTr("Handle passwords, hidden networks and any additional authentication in context. Show connection progress and useful failures without discarding the entered details unexpectedly. Discovery should run when needed while this drawer is in use, rather than being started by unrelated drawers."),
                qsTr("Include network details such as addresses and access status. Wired connections and VPN status or controls should also be reachable here so networking stays together. If that grows substantially, consider naming the destination Network rather than adding separate permanent bar buttons immediately.")
            ].join("\n\n")
        }
    }
}
