pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import "../../ui"

Surface {
    id: root
    required property var record
    property bool compact: false
    signal dismissed()
    signal actionRequested(string identifier)
    readonly property color accent: record.urgency === 2 ? Theme.danger : Theme.accent
    readonly property string urgencyText: record.urgency === 2 ? qsTr("Critical urgency") : record.urgency === 0 ? qsTr("Low urgency") : qsTr("Normal urgency")
    readonly property string urgencyIcon: record.urgency === 2 ? "triangle-alert" : record.urgency === 0 ? "arrow-down" : "info"
    function iconReference(value: string): string {
        return value.startsWith("image://icon/") ? value.slice("image://icon/".length).split("?")[0] : "";
    }
    function localSource(value: string): string {
        if (value.startsWith("image://icon/")) {
            const icon = iconReference(value);
            if (icon.startsWith("/")) return icon;
            return Quickshell.hasThemeIcon(icon) ? Quickshell.iconPath(icon, true) : "";
        }
        return value.startsWith("/") || value.startsWith("file:///") || value.startsWith("image://") ? value : "";
    }
    readonly property string appIconSource: {
        const icon = record.appIcon || "";
        if (icon.startsWith("/") || icon.includes(":")) return localSource(icon);
        if (icon && Quickshell.hasThemeIcon(icon)) return Quickshell.iconPath(icon, true);
        // libnotify may send an app icon as image-path rather than app_icon.
        const reference = iconReference(record.image || "");
        return reference && !reference.startsWith("/") && Quickshell.hasThemeIcon(reference) ? Quickshell.iconPath(reference, true) : "";
    }
    readonly property string artworkSource: {
        const value = record.image || "";
        const reference = iconReference(value);
        // Named theme icons belong in the header, never in an attachment area.
        return reference && !reference.startsWith("/") ? "" : localSource(value);
    }
    function actionIcon(action: var): string {
        const identifier = String(action.identifier || "").toLowerCase().replace(/[_\s]+/g, "-");
        const icons = {
            "open-folder": "folder-open", "folder-open": "folder-open", "show-in-folder": "folder-open",
            "play": "play", "media-playback-start": "play", "pause": "pause", "media-playback-pause": "pause",
            "next": "skip-forward", "media-skip-forward": "skip-forward", "previous": "skip-back", "media-skip-backward": "skip-back",
            "download": "download", "retry": "refresh-cw", "delete": "trash", "dismiss": "x", "close": "x"
        };
        if (icons[identifier]) return icons[identifier];
        const label = String(action.text || "").trim().toLowerCase();
        if (/^(?:open|show|view) (?:in |the |containing )*(?:folder|directory)\b/.test(label)) return "folder-open";
        if (/^(?:play|resume)\b/.test(label)) return "play";
        if (/^pause\b/.test(label)) return "pause";
        if (/^download\b/.test(label)) return "download";
        if (/^(?:retry|try again)$/.test(label)) return "refresh-cw";
        if (identifier === "open" || identifier === "document-open" || /^(?:open|view)\b/.test(label)) return "arrow-right";
        return "";
    }
    implicitHeight: content.implicitHeight + 28
    color: Theme.surface; radius: Theme.radius
    border.width: 1; border.color: Theme.border

    ColumnLayout {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
        spacing: 8
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            Item {
                Layout.preferredWidth: 24; Layout.preferredHeight: 24
                Image {
                    id: appIcon; anchors.fill: parent; sourceSize.width: 48; sourceSize.height: 48
                    fillMode: Image.PreserveAspectFit
                    source: root.appIconSource
                }
                Icon { anchors.centerIn: parent; width: 18; height: 18; name: "bell"; color: Theme.muted; visible: appIcon.status !== Image.Ready }
            }
            ShellText {
                Layout.fillWidth: true; Layout.minimumWidth: 0
                text: root.record.app; color: Theme.muted; font.pixelSize: Theme.smallFontSize; elide: Text.ElideRight
            }
            Item {
                id: urgencyIndicator
                objectName: "notificationUrgency:" + root.record.id
                readonly property string hint: root.urgencyText
                Layout.preferredWidth: 24; Layout.preferredHeight: 24
                Accessible.role: Accessible.StaticText; Accessible.name: hint
                Icon {
                    objectName: "notificationUrgencyIcon:" + root.record.id
                    anchors.centerIn: parent; width: 16; height: 16
                    name: root.urgencyIcon; color: root.record.urgency === 2 ? Theme.danger : Theme.muted
                }
                PassiveToolTip {
                    objectName: "notificationUrgencyTip:" + root.record.id
                    target: urgencyIndicator; text: urgencyIndicator.hint
                }
            }
            ShellText {
                visible: !root.compact; text: Qt.formatDateTime(new Date(root.record.timestamp * 1000), "d MMM, HH:mm")
                color: Theme.muted; font.pixelSize: Theme.smallFontSize
            }
            IconButton {
                objectName: "notificationDismiss:" + root.record.id
                implicitWidth: 26; implicitHeight: 26; padding: 5; iconName: "x"
                text: root.compact ? qsTr("Hide popup") : qsTr("Dismiss notification")
                onClicked: root.dismissed()
            }
        }
        ShellText {
            Layout.fillWidth: true; text: root.record.summary
            font.weight: Font.DemiBold; wrapMode: Text.Wrap
            maximumLineCount: root.compact ? 2 : 8; elide: Text.ElideRight
        }
        ShellText {
            visible: !!text; Layout.fillWidth: true; text: root.record.body
            color: Theme.muted; wrapMode: Text.Wrap
            maximumLineCount: root.compact ? 4 : 100; elide: Text.ElideRight
        }
        Image {
            objectName: "notificationArtwork:" + root.record.id
            visible: !!root.artworkSource && status === Image.Ready
            source: root.artworkSource; asynchronous: true
            Layout.fillWidth: true; Layout.preferredHeight: root.compact ? 100 : 160
            fillMode: Image.PreserveAspectFit; sourceSize.width: 760; sourceSize.height: 320
        }
        Rectangle {
            visible: root.record.progress >= 0
            Layout.fillWidth: true; implicitHeight: 4; radius: 2; color: Theme.raised
            Rectangle { height: parent.height; width: parent.width * Math.max(0, Math.min(100, root.record.progress)) / 100; radius: 2; color: root.accent }
        }
        Flow {
            id: actions
            Layout.fillWidth: true; spacing: 6
            visible: (root.record.actions || []).length > 0
            Repeater {
                model: root.record.actions || []
                ShellButton {
                    required property var modelData
                    objectName: "notificationAction:" + root.record.id + ":" + modelData.identifier
                    text: modelData.text; iconName: root.actionIcon(modelData)
                    width: Math.min(implicitWidth, actions.width)
                    onClicked: root.actionRequested(modelData.identifier)
                }
            }
        }
    }
}
