import QtQuick
import QtQuick.Controls

SpinBox {
    id: root
    property bool padded: false
    readonly property bool acceptableInput: input.acceptableInput && input.text.length > 0
    readonly property int number: acceptableInput ? Number(input.text) : -1
    signal accepted()
    function focusEditor(): void { input.forceActiveFocus(); input.selectAll(); }
    function commit(): void { if (acceptableInput) value = number; }
    function step(direction: int): void {
        commit();
        if (direction > 0) increase(); else decrease();
    }

    implicitWidth: 88
    implicitHeight: Theme.controlHeight + 4
    editable: true; wheelEnabled: false
    leftPadding: 8; rightPadding: 28; topPadding: 0; bottomPadding: 0
    font.family: Theme.monospaceFamily; font.pixelSize: Theme.fontSize
    inputMethodHints: Qt.ImhDigitsOnly
    textFromValue: value => padded ? String(value).padStart(2, "0") : String(value)
    valueFromText: text => Number(text)
    validator: IntValidator { bottom: root.from; top: root.to; locale: "C" }
    contentItem: TextInput {
        id: input
        text: root.displayText
        font: root.font; color: Theme.text
        selectionColor: Theme.accent; selectedTextColor: Theme.accentText
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        readOnly: !root.editable; selectByMouse: true
        maximumLength: Math.max(String(root.from).length, String(root.to).length)
        validator: root.validator; inputMethodHints: root.inputMethodHints
        Accessible.name: root.Accessible.name
        Keys.onUpPressed: root.step(1)
        Keys.onDownPressed: root.step(-1)
        onAccepted: if (root.acceptableInput) { root.value = root.number; root.accepted(); }
    }
    Connections { target: root.up; function onPressedChanged() { if (root.up.pressed) root.commit(); } }
    Connections { target: root.down; function onPressedChanged() { if (root.down.pressed) root.commit(); } }
    up.indicator: Rectangle {
        x: root.width - width; y: 0; width: 24; height: root.height / 2
        implicitWidth: 24; implicitHeight: 19
        radius: Theme.controlRadius
        color: root.up.pressed ? Theme.raised : root.up.hovered ? Theme.accentSurface : "transparent"
        Icon { anchors.centerIn: parent; name: "chevron-down"; rotation: 180; implicitWidth: 14; implicitHeight: 14; color: parent.enabled ? Theme.text : Theme.muted }
    }
    down.indicator: Rectangle {
        x: root.width - width; y: root.height / 2; width: 24; height: root.height / 2
        implicitWidth: 24; implicitHeight: 19
        radius: Theme.controlRadius
        color: root.down.pressed ? Theme.raised : root.down.hovered ? Theme.accentSurface : "transparent"
        Icon { anchors.centerIn: parent; name: "chevron-down"; implicitWidth: 14; implicitHeight: 14; color: parent.enabled ? Theme.text : Theme.muted }
    }
    background: Rectangle {
        color: Theme.surface; radius: Theme.controlRadius
        border.width: 1; border.color: root.activeFocus || input.activeFocus ? Theme.accent : Theme.border
    }
}
