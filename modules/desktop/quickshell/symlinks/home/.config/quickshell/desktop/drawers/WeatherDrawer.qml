import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Combine the current time and date with the weather for the selected place. Include a readable current condition, temperature and a compact hourly or daily forecast, with the last successful update clearly visible."),
                qsTr("Offer clock format, time-zone display and weather units or location preferences. Let a location be chosen deliberately rather than silently assuming it. If weather has not been configured, is stale or cannot be fetched, keep the clock usable and explain the weather state separately."),
                qsTr("The bar clock is already real; the weather icon is only a sample. Weather sources and any external account or location integration need their own implementation proposal. Events and notification history belong in the neighboring Events and notifications drawer.")
            ].join("\n\n")
        }
    }
}
