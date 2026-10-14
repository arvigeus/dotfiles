import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Show the applications that publish tray items, with recognizable icons, names and their current status. This is an overflow and access point for application-owned controls, not another copy of system settings."),
                qsTr("Preserve each item's normal activation, context menu and supported scroll actions. Make all entries reachable by keyboard, handle disappearing applications without stale menus, and retain a readable name when an icon is missing."),
                qsTr("The bar should eventually show the relevant live tray icons and use this drawer when there are more items than fit. An empty tray should say that no applications are publishing items; an unavailable tray service should be a different state.")
            ].join("\n\n")
        }
    }
}
