pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import "../../ui"

Button {
    id: root
    property bool active: true
    property bool busy: false
    property bool expanded: false
    property color indicatorColor: Theme.muted
    property string hint: expanded ? qsTr("Hide details") : qsTr("Show details")
    signal toggleRequested
    implicitWidth: marker.width + label.implicitWidth + glyph.width + line.spacing * 2 + leftPadding + rightPadding
    implicitHeight: 26
    horizontalPadding: 4
    verticalPadding: 2
    hoverEnabled: true
    Accessible.description: hint
    onClicked: toggleRequested()

    contentItem: Row {
        id: line
        spacing: 6
        Rectangle {
            id: marker
            anchors.verticalCenter: parent.verticalCenter
            width: 6
            height: 6
            radius: width / 2
            color: root.indicatorColor
        }
        ShellText {
            id: label
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, Math.max(0, line.width - marker.width - glyph.width - line.spacing * 2))
            text: root.text
            color: root.hovered || root.visualFocus ? Theme.text : Theme.muted
            font.pixelSize: Theme.smallFontSize
            elide: Text.ElideRight
        }
        Item {
            id: glyph
            anchors.verticalCenter: parent.verticalCenter
            width: 14
            height: 14
            BusySpinner {
                objectName: root.objectName + "Spinner"
                anchors.fill: parent
                visible: root.busy
                running: root.active && visible
                foreground: Theme.muted
            }
            Icon {
                objectName: root.objectName + "Chevron"
                anchors.fill: parent
                visible: !root.busy
                name: root.expanded ? "chevron-up" : "chevron-down"
                color: Theme.muted
            }
        }
    }
    background: ButtonBackground {
        highlighted: root.hovered || root.visualFocus
        pressed: root.down
    }
    PassiveToolTip {
        target: root
        text: root.text + "\n" + root.hint
    }
}
