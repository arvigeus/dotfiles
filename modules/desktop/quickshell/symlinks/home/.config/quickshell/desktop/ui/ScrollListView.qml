import QtQuick

// Shared native list behavior: immediate mouse-wheel steps, native touchpad
// gestures, and unchanged delegate clicks, focus and keyboard navigation.
ListView {
    id: root
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    WheelScroll {
        view: root
    }
}
