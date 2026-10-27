pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

RowLayout {
    id: root
    property var record: ({
            available: false,
            value: 0,
            reason: ""
        })
    property bool canAdjust: true
    property string label: qsTr("Brightness")
    signal edited(real value)
    spacing: 8
    IconButton {
        iconName: "sun"
        iconColor: root.record.available ? Theme.text : Theme.muted
        text: root.label
        hint: root.record.available ? qsTr("Brightness: %1%").arg(Math.round(root.record.value)) : root.record.reason
        onClicked: slider.forceActiveFocus()
    }
    Slider {
        id: slider
        objectName: root.objectName + ":slider"
        Layout.fillWidth: true
        implicitHeight: 34
        from: 1
        to: 100
        stepSize: 1
        enabled: root.canAdjust && root.record.available
        Accessible.name: root.label
        Accessible.description: root.record.available ? qsTr("Physical display brightness") : root.record.reason
        Binding {
            target: slider
            property: "value"
            value: root.record.available ? root.record.value : 1
            when: !slider.pressed
            restoreMode: Binding.RestoreNone
        }
        onMoved: root.edited(value)
        background: Rectangle {
            x: slider.leftPadding
            y: (slider.height - height) / 2
            width: slider.availableWidth
            height: 4
            radius: 2
            color: Theme.border
            Rectangle {
                width: slider.visualPosition * parent.width
                height: parent.height
                radius: 2
                color: slider.enabled ? Theme.accent : Theme.muted
            }
        }
        handle: Rectangle {
            x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
            y: (slider.height - height) / 2
            width: 14
            height: 14
            radius: 7
            color: slider.enabled ? Theme.text : Theme.muted
            border.width: slider.visualFocus ? 2 : 0
            border.color: Theme.accent
        }
    }
    ShellText {
        text: root.record.available ? Math.round(slider.pressed ? slider.value : root.record.value) + "%" : "—"
        color: slider.enabled ? Theme.text : Theme.muted
        font.pixelSize: Theme.smallFontSize
        Layout.preferredWidth: 36
        horizontalAlignment: Text.AlignRight
    }
}
