import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Show whether Bluetooth is enabled and which adapter is in use, followed by connected and paired devices. Include meaningful device names, connection state and device battery levels when they are reported."),
                qsTr("Offer connect, disconnect, pair and forget actions. Device discovery should be explicit and stop when it is no longer needed. Keep pairing progress, passkeys, confirmation requests, cancellation and rejection visible in the same context."),
                qsTr("Handle devices disappearing, adapters being switched off and unsupported device actions without leaving stale controls behind. The bar should eventually summarize enabled or connected state without requiring discovery to stay running.")
            ].join("\n\n")
        }
    }
}
