pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

ScrollView {
    id: root
    property var files: []
    property bool removable: false
    property real maximumHeight: 120
    signal removed(string id)
    signal previewRequested(var file)
    implicitHeight: Math.min(rows.implicitHeight, maximumHeight)
    contentWidth: availableWidth
    contentHeight: rows.implicitHeight
    clip: true
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    WheelScroll {
        view: root.contentItem as Flickable
        revealFocus: true
    }
    Flow {
        id: rows
        width: root.availableWidth
        spacing: 6
        Repeater {
            model: root.files
            delegate: Button {
                id: chip
                required property var modelData
                objectName: "assistantAttachment:" + modelData.id
                width: rows.width < 340 ? rows.width : (rows.width - rows.spacing) / 2
                height: 54
                padding: 6
                rightPadding: root.removable ? 34 : 6
                hoverEnabled: true
                text: modelData.name
                Accessible.name: qsTr("Preview %1").arg(text)
                onClicked: root.previewRequested(modelData)
                background: ButtonBackground {
                    idleColor: Theme.raised
                    highlighted: chip.hovered || chip.visualFocus
                    pressed: chip.down
                }
                contentItem: RowLayout {
                    spacing: 8
                    Image {
                        visible: chip.modelData.kind === "image"
                        source: visible ? chip.modelData.data : ""
                        cache: false
                        Layout.preferredWidth: 38
                        Layout.preferredHeight: 38
                        fillMode: Image.PreserveAspectCrop
                    }
                    Icon {
                        visible: chip.modelData.kind !== "image"
                        name: "file-text"
                        Layout.preferredWidth: 24
                        Layout.preferredHeight: 24
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 3
                        ShellText {
                            Layout.fillWidth: true
                            text: chip.modelData.name
                            elide: Text.ElideMiddle
                        }
                        ShellText {
                            Layout.fillWidth: true
                            font.pixelSize: Theme.smallFontSize
                            color: Theme.muted
                            text: chip.modelData.kind === "image" ? qsTr("%1 × %2").arg(chip.modelData.width).arg(chip.modelData.height) : qsTr("%1 KB text").arg(Math.max(1, Math.round(chip.modelData.size / 1024)))
                        }
                    }
                }
                IconButton {
                    objectName: "assistantAttachmentRemove:" + chip.modelData.id
                    visible: root.removable
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.rightMargin: 3
                    implicitWidth: 28
                    implicitHeight: 28
                    padding: 5
                    iconName: "x"
                    text: qsTr("Remove %1").arg(chip.modelData.name)
                    onClicked: root.removed(chip.modelData.id)
                }
                PassiveToolTip {
                    target: chip
                    text: qsTr("Preview %1").arg(chip.modelData.name)
                }
            }
        }
    }
}
