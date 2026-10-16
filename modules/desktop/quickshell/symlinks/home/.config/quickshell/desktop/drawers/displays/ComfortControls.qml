pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

ColumnLayout {
    id: root
    required property var service
    property bool active: false
    Layout.fillWidth: true
    spacing: 8
    RowLayout {
        Layout.fillWidth: true; Layout.topMargin: 8
        ShellText { text: qsTr("Night light"); font.weight: Font.DemiBold; Layout.fillWidth: true }
        Switch {
            id: toggle
            objectName: "nightLightEnabled"; Accessible.name: qsTr("Night light")
            checked: root.service.state.nightEnabled
            enabled: root.active && root.service.loaded && root.service.state.nightAvailable && !root.service.busy
            implicitWidth: 38; Layout.preferredWidth: 38
            implicitHeight: Theme.controlHeight; padding: 0; hoverEnabled: true
            onToggled: {
                const requested = checked; checked = Qt.binding(() => root.service.state.nightEnabled);
                root.service.run("night", {enabled: requested});
            }
            indicator: Rectangle {
                x: toggle.width - width; y: (toggle.height - height) / 2
                implicitWidth: 38; implicitHeight: 22; radius: height / 2
                color: toggle.checked ? Theme.accent : Theme.border; opacity: toggle.enabled ? 1 : 0.45
                Rectangle {
                    x: toggle.checked ? parent.width - width - 3 : 3
                    y: 3; width: 16; height: 16; radius: 8
                    color: toggle.checked ? Theme.accentText : Theme.text
                }
            }
            contentItem: Item {}
            background: ButtonBackground { idleColor: "transparent"; highlighted: toggle.visualFocus; pressed: toggle.down }
        }
    }
    ShellText {
        visible: root.service.error !== ""; text: root.service.error; color: Theme.danger
        Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText; font.pixelSize: Theme.smallFontSize
    }
}
