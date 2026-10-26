import QtQuick
import QtQuick.Controls
import "../movies"

Slider {
    id: root
    implicitHeight: MovieStyle.controlHeight
    leftPadding: 7; rightPadding: 7
    background: Rectangle {
        x: root.leftPadding; y: (root.height - height) / 2
        width: root.availableWidth; height: 4; radius: 2
        color: MovieStyle.border
        Rectangle { width: root.visualPosition * parent.width; height: parent.height; radius: 2; color: root.enabled ? MovieStyle.accent : MovieStyle.muted }
    }
    handle: Rectangle {
        x: root.leftPadding + root.visualPosition * (root.availableWidth - width)
        y: (root.height - height) / 2
        width: 12; height: 12; radius: 6
        color: root.enabled ? MovieStyle.text : MovieStyle.muted
        border.width: root.visualFocus || root.pressed ? 2 : 0
        border.color: MovieStyle.accent
    }
}
