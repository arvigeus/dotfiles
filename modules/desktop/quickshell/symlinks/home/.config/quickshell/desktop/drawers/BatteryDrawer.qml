import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Show system battery percentage, charging or discharging state, external power and a useful time-to-empty or time-to-full estimate when one is available. Distinguish fully charged, estimating and unavailable values. If there are multiple system batteries, make the combined summary and individual readings clear."),
                qsTr("Include battery health, current versus design capacity, cycle count and charging or discharging power when the hardware reports them. Offer charge limits only when supported, and show the actual applied setting rather than assuming that every machine supports the same limits."),
                qsTr("Keep battery care here and power/performance profiles in Performance, with a direct route between the two drawers. On machines without a system battery, adapt the summary rather than inventing a percentage. Bar percentage and charging indicators will eventually reflect real data; the current value is a sample.")
            ].join("\n\n")
        }
    }
}
