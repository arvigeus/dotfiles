import QtQuick
import QtQuick.Templates as T

// Add to any native Flickable/ListView/GridView. Native controls keep clicks
// and focus; the mouse-only step replaces Qt's wheel acceleration.
MouseArea {
    id: root

    required property Flickable view
    property int orientation: Qt.Vertical
    property bool verticalToHorizontal: false
    // Shared default in logical pixels. A horizontal strip can use its column width.
    property real wheelStep: 120
    // Scroll keyboard and programmatic focus inside the view into sight. Pointer
    // focus never scrolls, so a click cannot move its target away.
    property bool revealFocus: false

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

    Window.onActiveFocusItemChanged: {
        const focused = Window.activeFocusItem;
        if (!revealFocus || !focused)
            return;
        // Show the whole control (a SpinBox, not just its editor). Controls
        // record why they gained focus; plain items do not.
        let control = null;
        for (let item = focused; item; item = item.parent) {
            if (item === view.contentItem) {
                const reason = control?.focusReason;
                if (reason !== Qt.MouseFocusReason && reason !== Qt.ActiveWindowFocusReason)
                    reveal(control ?? focused);
                return;
            }
            if (!control && item instanceof T.Control)
                control = item as T.Control;
        }
    }

    // Layouts place newly shown items only when the window polishes, so a
    // reveal repeats once the next frame has settled their geometry.
    property Item pendingReveal: null
    Connections {
        target: root.pendingReveal ? root.Window.window : null
        function onAfterAnimating(): void {
            const item = root.pendingReveal;
            root.pendingReveal = null;
            if (item)
                root.show(item);
        }
    }

    function reveal(item: Item): void {
        show(item);
        pendingReveal = item;
        Window.window?.update();
    }

    function show(item: Item): void {
        const horizontal = orientation === Qt.Horizontal;
        const position = item.mapToItem(view.contentItem, 0, 0);
        const start = horizontal ? position.x : position.y;
        const end = start + (horizontal ? item.width : item.height);
        const size = horizontal ? view.width : view.height;
        const current = horizontal ? view.contentX : view.contentY;
        // Show the whole item, or its start when it is larger than the view.
        if (start < current)
            scrollTo(start);
        else if (end > current + size)
            scrollTo(Math.min(start, end - size));
    }

    // Returns whether the view moved; positions clamp to the scrollable range.
    function scrollTo(position: real): bool {
        if (!view.interactive)
            return false;
        const horizontal = orientation === Qt.Horizontal;
        const origin = horizontal ? view.originX : view.originY;
        const minimum = origin - (horizontal ? view.leftMargin : view.topMargin);
        const maximum = Math.max(minimum, origin + (horizontal ? view.contentWidth - view.width + view.rightMargin : view.contentHeight - view.height + view.bottomMargin));
        const current = horizontal ? view.contentX : view.contentY;
        const next = Math.max(minimum, Math.min(maximum, position));
        // Edge-spring note (Qt 6.12): ListView snaps programmatic overscroll back
        // immediately; revisit its fixup/Immediate behavior when trying rebound.
        if (next === current)
            return false;

        view.cancelFlick();
        if (horizontal)
            view.contentX = next;
        else
            view.contentY = next;
        return true;
    }

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

        const current = horizontal ? view.contentX : view.contentY;
        const distance = gesture ? amount : amount / 120 * wheelStep;
        // An exhausted inner view lets its parent scroll.
        event.accepted = scrollTo(current - distance);
    }
}
