pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"
import "../movies"

Item {
    id: root
    required property var store
    property bool busy: false
    readonly property var mainAction: store.primaryAction || ({
            type: "disabled",
            label: "Unavailable",
            enabled: false
        })
    readonly property var uninstallAction: (store.actions || []).find(action => action.type === "uninstall") || ({})
    readonly property var manageAction: (store.actions || []).find(action => action.type === "manage") || ({})
    readonly property color brandColor: store.store === "steam" ? "#1a9fff" : store.store === "gog" ? "#86328a" : "#111111"
    readonly property color actionColor: primary.down || more.down ? Qt.darker(brandColor, 1.15) : groupHover.hovered ? Qt.lighter(brandColor, 1.1) : brandColor
    readonly property string statusText: [store.statusTooltip || "", mainAction.tooltip || ""].filter(Boolean).join("\n")
    property alias popup: options
    signal actionRequested(var action)
    signal matchRequested(string store, string externalId)
    signal uninstallRequested(var action)
    signal urlRequested(string url)
    objectName: "gameStore:" + store.store
    implicitWidth: 230
    implicitHeight: 42
    HoverHandler {
        id: groupHover
    }

    MovieButton {
        id: primary
        objectName: "gameStoreAction:" + root.store.store
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: more.left
        text: root.mainAction.label || "Unavailable"
        enabled: !!root.mainAction.enabled && !root.busy
        Accessible.name: root.store.label + " · " + text
        Accessible.description: root.statusText
        contentItem: RowLayout {
            spacing: 8
            Image {
                objectName: "gameStoreArtwork:" + root.store.store
                Layout.preferredWidth: 24
                Layout.preferredHeight: 24
                source: Qt.resolvedUrl("stores/" + (root.store.store === "epic" ? "epicgames" : root.store.store) + ".svg")
                sourceSize.width: 48
                sourceSize.height: 48
                fillMode: Image.PreserveAspectFit
                Accessible.ignored: true
            }
            MovieText {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: primary.text
                font.bold: true
                color: "#ffffff"
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
            }
        }
        background: Rectangle {
            radius: MovieStyle.controlRadius
            topRightRadius: 0
            bottomRightRadius: 0
            color: root.actionColor
            border.width: primary.visualFocus ? 2 : 0
            border.color: MovieStyle.text
        }
        onClicked: {
            if (root.mainAction.type === "link")
                root.matchRequested(root.store.store, root.store.externalId || "");
            else if (root.mainAction.type === "buy")
                root.urlRequested(root.mainAction.url);
            else
                root.actionRequested(root.mainAction);
        }
        PassiveToolTip {
            target: primary
            text: root.statusText
            maximumLineCount: 12
        }
    }
    MovieIconButton {
        id: more
        objectName: "gameStoreOptions:" + root.store.store
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 36
        iconName: "chevron-down"
        iconColor: "#ffffff"
        text: "More " + root.store.label + " options"
        enabled: !root.busy
        background: Rectangle {
            radius: MovieStyle.controlRadius
            topLeftRadius: 0
            bottomLeftRadius: 0
            color: root.actionColor
            border.width: more.visualFocus ? 2 : 0
            border.color: MovieStyle.text
        }
        onClicked: options.visible ? options.close() : options.open()
        Menu {
            id: options
            popupType: Popup.Item
            y: more.height
            width: 220
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
            background: Rectangle {
                color: MovieStyle.surface
                border.color: MovieStyle.border
                radius: MovieStyle.controlRadius
            }
            MenuItem {
                text: "Open store page"
                visible: !!root.store.storeUrl
                height: visible ? implicitHeight : 0
                contentItem: MovieText {
                    text: parent.text
                }
                background: Rectangle {
                    color: parent.highlighted ? MovieStyle.accentSurface : "transparent"
                }
                onTriggered: root.urlRequested(root.store.storeUrl)
            }
            MenuItem {
                objectName: "gameStoreMatch:" + root.store.store
                text: "Edit store link"
                contentItem: MovieText {
                    text: parent.text
                }
                background: Rectangle {
                    color: parent.highlighted ? MovieStyle.accentSurface : "transparent"
                }
                onTriggered: root.matchRequested(root.store.store, root.store.externalId || "")
            }
            MenuItem {
                objectName: "gameStoreManage:" + root.store.store
                text: root.manageAction.label || "Manage in launcher"
                visible: !!root.manageAction.id
                height: visible ? implicitHeight : 0
                contentItem: MovieText {
                    text: parent.text
                }
                background: Rectangle {
                    color: parent.highlighted ? MovieStyle.accentSurface : "transparent"
                }
                onTriggered: root.actionRequested(root.manageAction)
            }
            MenuSeparator {
                visible: !!root.uninstallAction.id
                height: visible ? implicitHeight : 0
            }
            MenuItem {
                objectName: "gameStoreUninstall:" + root.store.store
                text: "Uninstall…"
                visible: !!root.uninstallAction.id
                height: visible ? implicitHeight : 0
                contentItem: MovieText {
                    text: parent.text
                    color: MovieStyle.danger
                }
                background: Rectangle {
                    color: parent.highlighted ? MovieStyle.accentSurface : "transparent"
                }
                onTriggered: root.uninstallRequested(root.uninstallAction)
            }
        }
    }
}
