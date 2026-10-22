pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Window
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import "../../ui"

Button {
    id: root
    objectName: "spacesProfile"
    property bool active: false
    property bool completed: false
    property var profile: ({name: "", username: Quickshell.env("USER") || "", avatar: ""})
    readonly property string profileHint: [profile.name, profile.username ? "@" + profile.username : ""].filter(Boolean).join("\n")
    readonly property bool hasAvatar: avatar.status === Image.Ready
    signal editRequested()
    function refresh(): void { if (!reader.running) reader.running = true; }
    Component.onCompleted: { completed = true; if (active) refresh(); }
    onActiveChanged: if (completed && active) refresh()

    implicitWidth: Theme.controlHeight; implicitHeight: Theme.controlHeight
    padding: 3; hoverEnabled: true; enabled: active
    text: qsTr("Edit user profile"); Accessible.name: text
    background: ButtonBackground { highlighted: root.hovered || root.visualFocus; pressed: root.down }
    contentItem: Item {
        Image {
            id: avatar
            anchors.fill: parent; visible: false
            source: root.profile.avatar || ""
            sourceSize.width: Math.ceil(width * Screen.devicePixelRatio)
            sourceSize.height: Math.ceil(height * Screen.devicePixelRatio)
            fillMode: Image.PreserveAspectCrop; cache: false
        }
        Rectangle {
            id: photoMask
            anchors.fill: parent; radius: width / 2
            layer.enabled: true; visible: false
        }
        MultiEffect {
            anchors.fill: parent; visible: root.hasAvatar
            source: avatar; maskEnabled: true; maskSource: photoMask
        }
        Icon {
            objectName: "spacesProfileFallback"
            anchors.centerIn: parent; width: 22; height: 22
            name: "user-round"; visible: !root.hasAvatar
            color: root.hovered || root.visualFocus ? Theme.accent : Theme.text
        }
    }
    PassiveToolTip { target: root; text: root.profileHint }
    onClicked: root.editRequested()

    Process {
        id: reader
        command: ["python3", Quickshell.shellPath("drawers/spaces/profile.py")]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.profile = JSON.parse(text); }
                catch (_) { console.warn("Could not read the local account profile."); }
            }
        }
        stderr: StdioCollector {}
    }
}
