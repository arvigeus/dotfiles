pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell
import "../ui"
import "spaces"

DrawerPage {
    id: root
    property var service: SessionService
    property var launch: argv => Apps.launch(argv)
    headerActions: Component {
        ProfileButton {
            active: root.active
            onEditRequested: {
                root.closeRequested();
                root.launch(["/usr/local/bin/account-tools"]);
            }
        }
    }
    escapeHandler: sessionActions.popupOpen ? () => {
        sessionActions.closePopup();
        return true;
    } : null
    onActiveChanged: if (active)
        service.refresh()

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gap
        DrawerColumn {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentSpacing: 8
            Repeater {
                model: SpaceState.entries
                Item {
                    id: row
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 52
                    readonly property bool highlighted: rowHover.hovered || entry.visualFocus || closeEntry.visualFocus
                    HoverHandler {
                        id: rowHover
                    }
                    Rectangle {
                        objectName: "spaceRowHighlight:" + row.modelData.id
                        anchors.fill: parent
                        z: -1
                        radius: Theme.controlRadius
                        color: row.highlighted ? Theme.accentSurface : "transparent"
                        border.width: row.highlighted ? 1 : 0
                        border.color: Theme.accent
                    }
                    RowLayout {
                        anchors.fill: parent
                        spacing: 4
                        ShellButton {
                            id: entry
                            readonly property var modelData: row.modelData
                            objectName: "space:" + modelData.id
                            Layout.fillWidth: true
                            Layout.preferredHeight: 52
                            idleColor: "transparent"
                            highlighted: row.highlighted
                            background: Item {}
                            enabled: root.active
                            text: modelData.name
                            iconName: modelData.icon
                            Accessible.description: SpaceState.runningIds.includes(modelData.id) ? qsTr("Running") : qsTr("Open %1").arg(modelData.name)
                            onClicked: SpaceState.open(modelData.id, root.screen)
                            contentItem: RowLayout {
                                spacing: 14
                                Icon {
                                    objectName: entry.objectName + "Icon"
                                    name: entry.iconName
                                    color: entry.highlighted ? Theme.accent : Theme.text
                                }
                                ShellText {
                                    Layout.fillWidth: true
                                    text: entry.text
                                    elide: Text.ElideRight
                                }
                            }
                        }
                        IconButton {
                            id: closeEntry
                            background: Item {}
                            iconColor: row.highlighted ? Theme.accent : Theme.muted
                            objectName: "closeSpace:" + row.modelData.id
                            visible: SpaceState.runningIds.includes(row.modelData.id)
                            iconName: "x"
                            text: qsTr("Close %1").arg(row.modelData.name)
                            onClicked: SpaceState.close(row.modelData.id)
                        }
                    }
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: Theme.border
        }
        SessionActions {
            id: sessionActions
            Layout.fillWidth: true
            active: root.active
            service: root.service
        }
    }
}
