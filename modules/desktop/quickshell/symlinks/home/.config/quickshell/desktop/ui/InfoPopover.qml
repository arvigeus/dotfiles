import QtQuick
import QtQuick.Controls

// Clickable, scrollable details. Keep essential values in the content, rather
// than a passive tooltip, so they can be selected and copied.
Popup {
    id: root
    required property Item button
    property bool active: false
    default property alias details: form.content
    signal dismissed()
    parent: button
    popupType: Popup.Item
    x: button.width - width; y: button.height + 8
    width: Math.min(400, Math.max(0, (Overlay.overlay?.width ?? 416) - 16))
    height: Math.min(form.contentHeight + topPadding + bottomPadding,
        Math.max(0, (Overlay.overlay?.height ?? 640) - 16))
    padding: 16; margins: 8; focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    background: Surface { color: Theme.background; radius: Theme.controlRadius }
    contentItem: DrawerColumn { id: form }
    onActiveChanged: if (!active) close()
    onClosed: {
        if (active && button.visible && button.enabled) button.forceActiveFocus();
        dismissed();
    }
}
