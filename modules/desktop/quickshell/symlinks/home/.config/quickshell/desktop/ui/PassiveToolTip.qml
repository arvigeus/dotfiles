import QtQuick
import QtQuick.Templates as T
import Quickshell

PopupWindow {
    id: root

    required property Item target
    property string text: target?.text || ""
    property int maximumLineCount: 6
    property bool ready: false
    readonly property bool hovered: target instanceof T.AbstractButton ? target.hovered : targetHover.hovered
    readonly property bool requested: !!target && hovered && !(target instanceof T.AbstractButton && target.down)
        && target.enabled && target.visible && text.length > 0

    HoverHandler {
        id: targetHover
        parent: root.target
        enabled: !(root.target instanceof T.AbstractButton)
    }

    onRequestedChanged: {
        ready = false;
        if (requested)
            delay.restart();
        else
            delay.stop();
    }
    Timer {
        id: delay
        interval: 800
        onTriggered: root.ready = true
    }

    // Native Controls tooltips can grab a panel's pointer input on Wayland.
    // This surface is informational: clicks pass through and focus stays put.
    grabFocus: false
    mask: Region {}
    visible: requested && ready
    anchor.item: target
    anchor.rect.x: ((target?.width || 0) - width) / 2
    anchor.rect.y: (target?.height || 0) + Theme.spacingSmall
    // Native window dimensions are integers; never round fractional text down.
    implicitWidth: Math.ceil(Math.min(label.implicitWidth, 480)) + Theme.spacingMedium * 2
    implicitHeight: Math.ceil(label.implicitHeight) + Theme.spacingMedium * 2
    color: "transparent"

    Surface {
        anchors.fill: parent
        radius: Theme.controlRadius
        color: Theme.background
        ShellText {
            id: label
            objectName: "tooltipText"
            anchors.centerIn: parent
            width: root.width - Theme.spacingMedium * 2
            // Changing window titles need text layout only while a tip is shown.
            text: root.visible ? root.text : ""
            wrapMode: Text.Wrap
            maximumLineCount: root.maximumLineCount
            elide: Text.ElideRight
        }
    }
}
