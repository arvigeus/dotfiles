import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Use one drawer for the overall performance picture, with separate CPU, GPU and memory sections. Start with current utilization, memory pressure and the active system power profile, then offer the supported profile choices with their effects on responsiveness, heat, noise and battery life."),
                qsTr("The CPU section should show useful load, frequency and temperature readings where available. The GPU section should identify the available graphics devices and show relevant utilization, graphics-memory use and temperature. Show fan readings only when the hardware provides them, and distinguish missing data from zero activity."),
                qsTr("Keep per-application GPU selection close to launching applications, with an explanation or route to it here. Whole-system graphics modes must be treated separately and state any logout or restart requirement. Avoid assuming every machine has switchable graphics or exposing unsupported tuning controls."),
                qsTr("Refresh detailed readings while this drawer is being used; a bar summary should remain lightweight and should not keep a sleeping GPU awake. Provide access to an existing system monitor for process-level investigation. Battery health and charging limits remain in Battery.")
            ].join("\n\n")
        }
    }
}
