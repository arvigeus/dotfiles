pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

ColumnLayout {
    id: root
    required property var record
    property bool active: false
    signal edited(real value)
    spacing: 4
    RowLayout {
        Layout.fillWidth: true; spacing: 12
        Slider {
            id: slider
            objectName: "keyboardBacklightSlider:" + root.record.key
            Layout.fillWidth: true; implicitHeight: Theme.controlHeight
            from: 0; to: Math.max(1, root.record.maximum); stepSize: 1
            snapMode: Slider.SnapAlways
            enabled: root.active && root.record.available
            Accessible.name: qsTr("Keyboard backlight brightness")
            Accessible.description: root.record.key
            Binding { target: slider; property: "value"; value: root.record.value; when: !slider.pressed; restoreMode: Binding.RestoreNone }
            onMoved: root.edited(value)
            background: Rectangle {
                x: slider.leftPadding; y: (slider.height - height) / 2
                width: slider.availableWidth; height: 4; radius: 2; color: Theme.border
                Rectangle { width: slider.visualPosition * parent.width; height: parent.height; radius: 2; color: slider.enabled ? Theme.accent : Theme.muted }
            }
            handle: Rectangle {
                x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
                y: (slider.height - height) / 2
                width: 14; height: 14; radius: 7; color: slider.enabled ? Theme.text : Theme.muted
                border.width: slider.visualFocus ? 2 : 0; border.color: Theme.accent
            }
        }
        ShellText {
            readonly property real level: slider.pressed ? slider.value : root.record.value
            text: !root.record.available ? "—" : level === 0 ? qsTr("Off") : Math.round(level * 100 / root.record.maximum) + "%"
            Layout.preferredWidth: 40; horizontalAlignment: Text.AlignRight
            color: slider.enabled ? Theme.text : Theme.muted; font.pixelSize: Theme.smallFontSize
        }
    }
    ShellText {
        visible: root.record.reason !== ""; text: root.record.reason
        Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.smallFontSize
    }
}
