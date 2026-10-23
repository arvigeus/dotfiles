pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
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
            onEditRequested: { root.closeRequested(); root.launch(["/usr/local/bin/account-tools"]); }
        }
    }
    escapeHandler: sessionActions.popupOpen ? () => { sessionActions.closePopup(); return true; } : null
    onActiveChanged: if (active) service.refresh()

    ColumnLayout {
        anchors.fill: parent; spacing: Theme.gap
        DrawerColumn {
            Layout.fillWidth: true; Layout.fillHeight: true
            contentSpacing: 8
            Repeater {
                model: [
                    {id: "movies", name: qsTr("Movies"), icon: "film"},
                    {id: "series", name: qsTr("TV Series"), icon: "tv"},
                    {id: "music", name: qsTr("Music"), icon: "music"},
                    {id: "radio", name: qsTr("Radio"), icon: "boom-box"},
                    {id: "pictures", name: qsTr("Pictures"), icon: "image"},
                    {id: "games", name: qsTr("Games"), icon: "gamepad-2"},
                    {id: "books", name: qsTr("Books"), icon: "book-open"}
                ]
                ShellButton {
                    id: entry
                    required property var modelData
                    objectName: "space:" + modelData.id
                    Layout.fillWidth: true; Layout.preferredHeight: 52
                    idleColor: "transparent"
                    enabled: root.active
                    text: modelData.name; iconName: modelData.icon
                    // Navigation is intentionally deferred; these are placeholders.
                    Accessible.description: qsTr("Not available yet")
                    contentItem: RowLayout {
                        spacing: 14
                        Icon { objectName: entry.objectName + "Icon"; name: entry.iconName; color: entry.highlighted ? Theme.accent : Theme.text }
                        ShellText { Layout.fillWidth: true; text: entry.text; elide: Text.ElideRight }
                    }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
        SessionActions { id: sessionActions; Layout.fillWidth: true; active: root.active; service: root.service }
    }
}
