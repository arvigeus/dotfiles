pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../ui"

Card {
    id: root
    required property var device
    property bool active: false
    property var service: controls
    property bool previewing: false
    readonly property var privacy: service.state.controls.find(control => control.key === "privacy")
    readonly property bool blocked: !!privacy?.value
    readonly property bool settingsOpen: settings.visible
    property Component previewComponent: Component { WebcamPreview { device: root.device; active: root.active && root.previewing && !root.blocked } }
    signal settingsRequested()
    signal previewRequested()
    function closeSettings(): void { settings.close(); }
    Layout.fillWidth: true
    implicitHeight: content.implicitHeight + 24
    WebcamService { id: controls; device: String(root.device.id); active: root.active && root.service === controls }
    onActiveChanged: if (!active) { previewing = false; settings.close(); }
    onBlockedChanged: if (blocked) previewing = false
    ColumnLayout {
        id: content
        anchors.fill: parent; anchors.margins: 12; spacing: 8
        RowLayout {
            Layout.fillWidth: true; spacing: 6
            ShellText {
                id: cameraName
                Layout.fillWidth: true; text: root.device.description; font.weight: Font.DemiBold
                elide: Text.ElideRight; textFormat: Text.PlainText
                PassiveToolTip { target: cameraName; text: root.device.description }
            }
            ShellSwitch {
                objectName: "webcamEnabled"
                visible: !!root.privacy
                text: root.privacy?.writable ? qsTr("Enable camera capture") : qsTr("Camera privacy shutter")
                checked: !root.blocked
                enabled: root.active && !!root.privacy?.writable
                onToggled: {
                    const value = checked ? 0 : 1;
                    checked = Qt.binding(() => !root.blocked);
                    root.service.setControl("privacy", value);
                }
            }
            IconButton {
                id: options
                objectName: "webcamSettings"
                iconName: "settings"; text: qsTr("Camera settings")
                onClicked: {
                    if (settings.visible) settings.close();
                    else { root.settingsRequested(); root.service.refresh(); settings.open(); }
                }
                InfoPopover {
                    id: settings
                    objectName: "webcamSettingsPopup"
                    button: options; active: root.active
                    WebcamControls { service: root.service }
                }
            }
        }
        ShellText {
            visible: root.blocked || root.service.error !== ""
            text: root.blocked ? qsTr("Camera capture blocked") : root.service.error
            Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText
            color: root.blocked ? Theme.muted : Theme.warning; font.pixelSize: Theme.smallFontSize
        }
        ShellButton {
            objectName: "webcamTest"
            Layout.fillWidth: true; iconName: root.previewing ? "x" : "camera"
            text: root.previewing ? qsTr("Stop preview") : qsTr("Test webcam")
            enabled: root.active && !root.blocked
            checked: root.previewing
            onClicked: {
                root.previewing = !root.previewing;
                if (root.previewing) root.previewRequested();
            }
        }
        Loader {
            objectName: "webcamPreview"
            Layout.fillWidth: true
            active: root.active && root.previewing && !root.blocked
            visible: active
            sourceComponent: root.previewComponent
        }
    }
}
