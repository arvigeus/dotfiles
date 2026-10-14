import QtQuick
import "../ui"

DrawerPage {
    DrawerColumn {
        anchors.fill: parent

        DrawerBrief {
            text: [
                qsTr("Show connected displays and the current arrangement. Provide resolution, refresh rate, scale, rotation and enabled state for each display, with supported placement controls and a clear indication of which physical output is being edited."),
                qsTr("Include brightness for displays that support it, showing unavailable controls honestly. Physical backlight brightness should remain distinct from color or HDR adjustments. Offer saved arrangements only when their behavior for docking, reconnecting and unknown displays has been defined."),
                qsTr("Keep at least one usable display available. Preview arrangement changes and provide a way back if the result cannot be used; handle unplugging a display during editing without losing access to the remaining screens.")
            ].join("\n\n")
        }
    }
}
