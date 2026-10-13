import QtQuick

// Add to any native Flickable/ListView/GridView. Native controls keep clicks
// and focus; the mouse-only step replaces Qt's wheel acceleration.
MouseArea {
    id: root

    required property Flickable view
    property int orientation: Qt.Vertical
    property bool verticalToHorizontal: false
    // Shared default in logical pixels. A horizontal strip can use its column width.
    property real wheelStep: 120

    // Behind content controls, but before the view's own wheel handler. Offset
    // the moving contentItem so this area always covers the visible viewport.
    parent: view.contentItem
    x: view.contentX
    y: view.contentY
    width: view.width
    height: view.height
    z: -1
    acceptedButtons: Qt.NoButton
    // Qt keeps touchpad precision and inertia. Horizontal strips can opt in
    // when they explicitly map vertical gestures to horizontal movement.
    scrollGestureEnabled: false
    onWheel: event => scroll(event)

    function scroll(event: var): void {
        event.accepted = false;
        if (!view.interactive)
            return;

        // Qt 6.12 mouse wheels can have pixelDelta too. Only phased gestures
        // use pixels; unphased wheels use proportional angle deltas, including
        // high-resolution wheels with less than one 120-unit notch.
        const gesture = event.phase !== Qt.NoScrollPhase;
        if (gesture && !scrollGestureEnabled)
            return;
        const delta = gesture ? event.pixelDelta : event.angleDelta;
        const horizontal = orientation === Qt.Horizontal;
        const amount = horizontal ? delta.x || (verticalToHorizontal ? delta.y : 0) : delta.y;
        if (!amount) {
            event.accepted = gesture && scrollGestureEnabled;
            return;
        }

        const origin = horizontal ? view.originX : view.originY;
        const minimum = origin - (horizontal ? view.leftMargin : view.topMargin);
        const maximum = Math.max(minimum, origin
            + (horizontal ? view.contentWidth - view.width + view.rightMargin
                : view.contentHeight - view.height + view.bottomMargin));
        const current = horizontal ? view.contentX : view.contentY;
        const distance = gesture ? amount : amount / 120 * wheelStep;
        const next = Math.max(minimum, Math.min(maximum, current - distance));
        // Edge-spring note (Qt 6.12): ListView snaps programmatic overscroll back
        // immediately; revisit its fixup/Immediate behavior when trying rebound.
        // An exhausted inner view lets its parent scroll.
        if (next === current)
            return;

        view.cancelFlick();
        if (horizontal)
            view.contentX = next;
        else
            view.contentY = next;
        event.accepted = true;
    }
}
