import QtQuick

Rectangle {
    // Shared hover/active appearance: accent-tinted fill and matching border.
    // Bind highlighted to the control's hover/active state, independent of favorites.
    property bool highlighted: false
    property bool pressed: false
    property color idleColor: "transparent"
    property color idleBorderColor: "transparent"

    radius: Theme.controlRadius
    color: pressed ? Theme.raised : highlighted ? Theme.accentSurface : idleColor
    border.width: 1
    border.color: highlighted ? Theme.accent : idleBorderColor
}
