pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../../ui"

ColumnLayout {
    id: root
    required property var service
    Layout.fillWidth: true
    spacing: 12
    KeyedModel {
        id: controls
        values: root.service.state.controls.filter(control => control.key !== "privacy")
        keyField: "key"
    }
    ShellText {
        visible: !controls.values.length
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
        text: root.service.loaded ? qsTr("No adjustable camera controls reported.") : qsTr("Reading camera controls…")
    }
    Repeater {
        model: controls
        delegate: ColumnLayout {
            id: control
            required property var modelData
            readonly property var record: modelData
            Layout.fillWidth: true
            spacing: 4
            RowLayout {
                Layout.fillWidth: true
                ShellText {
                    text: control.record.label
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
                ShellSwitch {
                    objectName: "webcamControl:" + control.record.key
                    visible: control.record.kind === "bool"
                    text: control.record.label
                    checked: !!control.record.value
                    enabled: root.service.active && control.record.writable
                    onToggled: {
                        const value = checked ? 1 : 0;
                        checked = Qt.binding(() => !!control.record.value);
                        root.service.setControl(control.record.key, value);
                    }
                }
            }
            ShellChoice {
                objectName: "webcamControl:" + control.record.key
                Layout.fillWidth: true
                visible: ["menu", "intmenu"].includes(control.record.kind)
                model: control.record.choices
                textRole: "label"
                currentIndex: control.record.choices.findIndex(choice => choice.value === control.record.value)
                enabled: root.service.active && control.record.writable
                Accessible.name: control.record.label
                onActivated: index => root.service.setControl(control.record.key, control.record.choices[index].value)
            }
            Slider {
                id: slider
                objectName: "webcamControl:" + control.record.key
                Layout.fillWidth: true
                implicitHeight: Theme.controlHeight
                visible: control.record.kind === "int"
                enabled: root.service.active && control.record.writable
                Accessible.name: control.record.label
                from: control.record.minimum
                to: control.record.maximum
                stepSize: control.record.step
                Binding {
                    target: slider
                    property: "value"
                    value: control.record.value
                    when: !slider.pressed
                    restoreMode: Binding.RestoreNone
                }
                property bool moved: false
                onMoved: {
                    if (pressed)
                        moved = true;
                    else
                        root.service.setControl(control.record.key, Math.round(value));
                }
                onPressedChanged: if (!pressed && moved) {
                    moved = false;
                    root.service.setControl(control.record.key, Math.round(value));
                }
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
        }
    }
}
