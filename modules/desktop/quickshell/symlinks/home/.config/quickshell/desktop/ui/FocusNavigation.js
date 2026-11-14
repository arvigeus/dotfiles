.pragma library

function belongsTo(scope, item) {
    for (let current = item; current; current = current.parent) {
        if (current === scope)
            return true;
    }
    return false;
}

function collectionFor(scope, item) {
    for (let current = item; current && current !== scope; current = current.parent) {
        if (typeof current.positionViewAtIndex === "function" && current.keyNavigationEnabled)
            return current;
    }
    return null;
}

// Use Qt's focus chain so text fields, native controls and virtualized views
// remain single navigation targets. Hidden/background Space trees are skipped.
function step(scope, focused, direction) {
    if (!scope)
        return false;
    const start = focused || scope;
    const currentTarget = collectionFor(scope, start) || start;
    let item = start;
    for (let count = 0; count < 4096; ++count) {
        item = item.nextItemInFocusChain(direction > 0);
        if (!item || item === start)
            return false;
        const collection = collectionFor(scope, item);
        const target = collection || item;
        if (target !== currentTarget && (collection || item.activeFocusOnTab) && target.visible && target.enabled && target.width > 0 && target.height > 0 && belongsTo(scope, target)) {
            target.forceActiveFocus(direction > 0 ? Qt.TabFocusReason : Qt.BacktabFocusReason);
            return true;
        }
    }
    return false;
}

// Native views/text fields handle their own arrows first. Only unhandled keys
// reach this fallback, allowing ordinary buttons/forms to work without a mouse.
function arrow(scope, focused, event) {
    if (event.modifiers !== Qt.NoModifier || collectionFor(scope, focused))
        return false;
    const previous = event.key === Qt.Key_Up || event.key === Qt.Key_Left;
    const next = event.key === Qt.Key_Down || event.key === Qt.Key_Right;
    return (previous || next) && step(scope, focused, previous ? -1 : 1);
}
