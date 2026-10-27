pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

Surface {
    id: root
    property string title: ""
    property string summary: ""
    property string iconName: ""
    property bool collapsible: true
    property bool expanded: false
    property Component action: null
    property Component leading: null
    property string hint: ""
    property bool flat: false
    default property alias contents: body.data
    readonly property bool showContents: !collapsible || expanded
    function toggle(): void {
        expanded = !expanded;
    }
    Layout.fillWidth: true
    implicitHeight: layout.implicitHeight + (showContents && !flat ? 24 : 8)
    color: showContents && !flat ? Theme.surface : "transparent"
    border.width: showContents && !flat ? 1 : 0
    data: ColumnLayout {
        id: layout
        anchors.fill: parent
        anchors.margins: root.showContents && !root.flat ? 12 : 4
        spacing: root.showContents ? 8 : 0
        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            Loader {
                active: root.leading !== null
                sourceComponent: root.leading
            }
            Button {
                id: heading
                objectName: root.objectName + "Heading"
                Layout.fillWidth: true
                implicitHeight: Theme.controlHeight
                padding: 0
                hoverEnabled: true
                text: root.title
                Accessible.name: root.title
                Accessible.role: root.collapsible ? Accessible.Button : Accessible.Heading
                onClicked: if (root.collapsible)
                    root.toggle()
                contentItem: RowLayout {
                    spacing: 8
                    Item {
                        visible: root.leading === null && root.iconName !== ""
                        implicitWidth: Theme.controlHeight
                        implicitHeight: Theme.controlHeight
                        Icon {
                            anchors.centerIn: parent
                            width: 20
                            height: 20
                            name: root.iconName
                            color: root.collapsible && (heading.hovered || heading.visualFocus) ? Theme.accent : Theme.muted
                        }
                    }
                    ShellText {
                        text: root.title
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    ShellText {
                        text: root.summary
                        color: Theme.muted
                        font.pixelSize: Theme.smallFontSize
                        elide: Text.ElideRight
                        Layout.maximumWidth: 140
                    }
                    Icon {
                        visible: root.collapsible
                        name: root.expanded ? "chevron-up" : "chevron-down"
                        width: 16
                        height: 16
                        color: Theme.muted
                    }
                }
                background: ButtonBackground {
                    highlighted: root.collapsible && (heading.hovered || heading.visualFocus)
                }
                PassiveToolTip {
                    target: heading
                    text: root.hint
                    maximumLineCount: 18
                }
            }
            Loader {
                active: root.action !== null
                sourceComponent: root.action
            }
        }
        ColumnLayout {
            id: body
            visible: root.showContents
            Layout.fillWidth: true
            spacing: 8
        }
    }
}
