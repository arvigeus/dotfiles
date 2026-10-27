import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell

RowLayout {
    id: root
    required property string label
    property string value: ""
    property string copyText: value
    property string placeholder: qsTr("Unavailable")
    property bool copied: false
    Layout.fillWidth: true
    spacing: 8
    onCopyTextChanged: copied = false
    ColumnLayout {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: 2
        ShellText {
            text: root.label
            color: Theme.muted
            font.pixelSize: Theme.smallFontSize
            Layout.fillWidth: true
            wrapMode: Text.Wrap
        }
        ShellText {
            objectName: root.objectName ? root.objectName + "Value" : ""
            text: root.value || root.placeholder
            Layout.fillWidth: true
            wrapMode: Text.WrapAnywhere
        }
    }
    Button {
        id: copy
        objectName: root.objectName ? root.objectName + "Copy" : ""
        text: root.copied ? qsTr("Copied") : qsTr("Copy %1").arg(root.label)
        enabled: root.copyText !== ""
        implicitWidth: Theme.controlHeight
        implicitHeight: Theme.controlHeight
        padding: 8
        hoverEnabled: true
        Accessible.name: text
        onClicked: {
            Quickshell.clipboardText = root.copyText;
            root.copied = true;
            reset.restart();
        }
        contentItem: Icon {
            name: root.copied ? "check" : "copy"
            color: copy.hovered || copy.visualFocus ? Theme.accent : Theme.muted
        }
        background: ButtonBackground {
            highlighted: copy.hovered || copy.visualFocus
            pressed: copy.down
        }
        PassiveToolTip {
            target: copy
        }
    }
    Timer {
        id: reset
        interval: 1500
        onTriggered: root.copied = false
    }
}
