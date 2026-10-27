import QtQuick
import QtQuick.Controls
import "."

PlainInputField {
    id: root
    property bool clearButtonEnabled: true
    property string clearAccessibleName: qsTr("Clear text")
    signal cleared

    rightPadding: Theme.controlHeight + 4

    Button {
        id: clearButton
        objectName: root.objectName ? root.objectName + "Clear" : "clearTextButton"
        anchors.right: parent.right
        anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        width: Theme.controlHeight - 4
        height: Theme.controlHeight - 4
        padding: 6
        hoverEnabled: true
        visible: root.clearButtonEnabled && !!root.text
        enabled: root.enabled
        Accessible.name: root.clearAccessibleName
        onClicked: {
            root.clear();
            root.forceActiveFocus();
            root.cleared();
        }
        contentItem: Icon {
            name: "x"
            color: clearButton.hovered || clearButton.visualFocus ? Theme.accent : Theme.muted
        }
        background: Rectangle {
            radius: Theme.controlRadius
            color: clearButton.hovered || clearButton.visualFocus ? Theme.raised : "transparent"
        }
        PassiveToolTip {
            target: clearButton
            text: root.clearAccessibleName
        }
    }
}
