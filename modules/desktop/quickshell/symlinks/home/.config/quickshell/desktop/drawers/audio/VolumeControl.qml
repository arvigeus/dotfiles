pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"
import "../../ui/AudioIcons.js" as AudioIcons

RowLayout {
    id: root
    property real volume: 0
    property bool muted: false
    property real maximum: 100
    readonly property real displayMaximum: Math.max(maximum, volume)
    property string label: qsTr("Volume")
    property bool canVolume: true
    property bool canMute: true
    property bool showPercentage: true
    property bool microphone: false
    property string muteHint: ""
    signal volumeEdited(real value)
    signal muteClicked
    spacing: 8
    IconButton {
        objectName: root.objectName + ":mute"
        iconName: root.microphone ? (root.muted ? "mic-off" : "mic") : AudioIcons.volume(root.volume, root.muted)
        text: root.muteHint || (root.microphone ? (root.muted ? qsTr("Turn on microphone") : qsTr("Turn off microphone")) : root.muted ? qsTr("Unmute %1").arg(root.label) : qsTr("Mute %1").arg(root.label))
        iconColor: root.volume > 100 || root.muted ? Theme.accent : Theme.text
        enabled: root.canMute
        onClicked: root.muteClicked()
    }
    Slider {
        id: slider
        objectName: root.objectName + ":slider"
        Layout.fillWidth: true
        implicitHeight: 34
        property real dragMaximum: root.displayMaximum
        from: 0
        to: pressed ? dragMaximum : root.displayMaximum
        stepSize: 1
        onPressedChanged: if (pressed)
            dragMaximum = root.displayMaximum
        enabled: root.canVolume
        Accessible.name: root.label
        Accessible.description: root.muted ? (root.canVolume ? qsTr("Muted. Adjusting volume keeps it muted.") : qsTr("Muted")) : qsTr("Adjustment limit %1 percent").arg(root.maximum)
        Binding {
            target: slider
            property: "value"
            value: Math.min(root.volume, slider.to)
            when: !slider.pressed
            restoreMode: Binding.RestoreNone
        }
        onMoved: root.volumeEdited(value)
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
                color: root.muted ? Theme.muted : slider.value > 100 ? Theme.warning : Theme.accent
            }
            Rectangle {
                visible: slider.to > 100
                x: parent.width * 100 / slider.to
                y: -3
                width: 1
                height: 10
                color: Theme.text
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
        visible: root.showPercentage
        text: Math.round(slider.pressed ? slider.value : root.volume) + "%"
        color: root.volume > 100 ? Theme.warning : root.muted ? Theme.muted : Theme.text
        font.family: Theme.monospaceFamily
        horizontalAlignment: Text.AlignRight
        Layout.preferredWidth: 48
    }
}
