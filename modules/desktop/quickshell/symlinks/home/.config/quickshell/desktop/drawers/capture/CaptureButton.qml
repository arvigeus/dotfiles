pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

Item {
    id: root
    property string text: ""
    property string iconName: ""
    property string hint: text
    property bool highlighted: false
    property bool actionEnabled: true
    property bool optionsEnabled: true
    readonly property alias menuButton: options
    readonly property bool hovered: action.hovered || options.hovered
    readonly property bool focused: action.visualFocus || options.visualFocus
    signal clicked
    signal optionsClicked
    implicitHeight: 68
    implicitWidth: 180

    ButtonBackground {
        objectName: root.objectName + "Background"
        anchors.fill: parent
        idleColor: Theme.raised
        highlighted: root.highlighted || root.hovered || root.focused
        pressed: action.down || options.down
    }
    Button {
        id: action
        objectName: root.objectName + "Action"
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: options.left
        padding: 6
        hoverEnabled: true
        enabled: root.enabled && root.actionEnabled
        Accessible.name: root.text
        opacity: enabled ? 1 : 0.45
        onClicked: root.clicked()
        background: Item {}
        contentItem: ColumnLayout {
            spacing: 5
            Icon {
                name: root.iconName
                color: root.highlighted || root.hovered || root.focused ? Theme.accent : Theme.text
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 22
                Layout.preferredHeight: 22
            }
            ShellText {
                text: root.text
                font.pixelSize: Theme.smallFontSize
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
            }
        }
        PassiveToolTip {
            target: action
            text: root.hint
        }
    }
    Rectangle {
        anchors.right: options.left
        anchors.verticalCenter: parent.verticalCenter
        width: 1
        height: parent.height - 20
        color: Theme.border
    }
    Button {
        id: options
        objectName: root.objectName + "Options"
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 32
        padding: 7
        hoverEnabled: true
        enabled: root.enabled && root.optionsEnabled
        text: qsTr("%1 options").arg(root.text)
        Accessible.name: text
        opacity: enabled ? 1 : 0.45
        onClicked: root.optionsClicked()
        background: Item {}
        contentItem: Icon {
            name: "chevron-down"
            color: root.highlighted || root.hovered || root.focused ? Theme.accent : Theme.text
        }
        PassiveToolTip {
            target: options
        }
    }
}
