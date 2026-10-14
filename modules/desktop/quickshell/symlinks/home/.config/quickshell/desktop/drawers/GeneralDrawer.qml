pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../ui"

DrawerPage {
    id: root

    DrawerColumn {
        anchors.fill: parent

        ShellText {
            text: qsTr("Shell theme")
            font.weight: Font.DemiBold
            Layout.fillWidth: true
        }

        ButtonGroup { id: modeGroup }
        Repeater {
            id: modes
            model: ["dark", "light"]
            // With lazy creation count can change before itemAt() is populated.
            onItemAdded: (index, item) => { if ((item as RadioButton)?.checked) root.initialFocus = item; }
            delegate: RadioButton {
                id: modeButton
                required property string modelData
                objectName: "theme-" + modelData
                text: modelData === "dark" ? qsTr("Dark") : qsTr("Light")
                checked: Theme.mode === modelData
                onCheckedChanged: if (checked) root.initialFocus = modeButton
                ButtonGroup.group: modeGroup
                Layout.fillWidth: true
                implicitHeight: Theme.pillHeight
                padding: Theme.gap
                hoverEnabled: true
                onClicked: Theme.setMode(modelData)
                indicator: Rectangle {
                    x: modeButton.leftPadding
                    y: (modeButton.height - height) / 2
                    width: 18; height: 18; radius: 9
                    color: "transparent"
                    border.color: modeButton.checked ? Theme.accent : Theme.muted
                    Rectangle {
                        anchors.centerIn: parent
                        width: 10; height: 10; radius: 5
                        visible: modeButton.checked
                        color: Theme.accent
                    }
                }
                contentItem: ShellText {
                    text: modeButton.text
                    leftPadding: 18 + Theme.gap
                    verticalAlignment: Text.AlignVCenter
                }
                background: ButtonBackground {
                    highlighted: modeButton.activeFocus
                    pressed: modeButton.down
                    idleColor: modeButton.hovered ? Theme.raised : Theme.surface
                }
            }
        }

        DrawerBrief {
            text: [
                qsTr("Collect shell appearance and persistent desktop preferences that do not have a more specific home. Start with the existing light/dark theme choice; expand to wallpaper, shared application appearance and relevant accessibility or bar-presentation options as those capabilities are designed."),
                qsTr("Keep persistent screen-blanking, automatic-locking and idle preferences understandable, and distinguish saved defaults from temporary overrides. Temporary Stay awake and Keep screen on controls, along with lock, logout and power actions, belong in the left Spaces drawer."),
                qsTr("Network, sound, microphone, displays, storage, battery and performance each have their own direct drawer. General should stay small rather than becoming another settings directory or navigation stack. The theme controls above already work; the rest of this text describes proposed content.")
            ].join("\n\n")
        }
    }
}
