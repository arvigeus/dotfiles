pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

Button {
    id: root
    property string iconName: ""
    property bool connected: false
    property string hint: ""
    property bool wireless: false
    property int strength: 0
    property bool secured: false
    highlighted: hovered || visualFocus
    readonly property color foreground: highlighted ? Theme.accent : connected ? Theme.text : Theme.muted
    Layout.fillWidth: true
    Layout.leftMargin: 28
    implicitHeight: 40
    padding: 6
    hoverEnabled: true
    Accessible.name: text
    Accessible.description: hint
    opacity: enabled ? 1 : 0.5
    contentItem: RowLayout {
        spacing: 10
        Loader {
            Layout.preferredWidth: 26
            Layout.preferredHeight: 26
            sourceComponent: root.wireless ? wifi : standard
        }
        ShellText {
            Layout.fillWidth: true
            text: root.text
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.foreground
        }
    }
    Component {
        id: wifi
        WifiIcon { strength: root.strength; secured: root.secured; foreground: root.foreground }
    }
    Component {
        id: standard
        Item { Icon { anchors.centerIn: parent; width: 22; height: 22; name: root.iconName; color: root.foreground } }
    }
    background: ButtonBackground { highlighted: root.highlighted; pressed: root.down }
    PassiveToolTip { target: root; text: root.hint; maximumLineCount: 18 }
}
