import QtQuick

// Shared native list behavior: immediate mouse-wheel steps, native touchpad
// gestures, and unchanged delegate clicks, focus and keyboard navigation.
// Tabbing into a delegate scrolls it into view.
ListView {
    id: root
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    WheelScroll {
        view: root
        revealFocus: true
    }
}
