pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

DrawerActionButton {
    id: root
    property var service: CleanupService
    property bool active: false
    readonly property bool popupOpen: editor.visible
    readonly property alias popup: editor
    signal popupOpened
    property var selected: []
    readonly property var selectableKeys: {
        const keys = service.entries.filter(entry => entry.available).map(entry => entry.id);
        return keys.includes("mise-tools") ? keys.filter(key => key !== "mise-unused") : keys;
    }
    readonly property bool allSelected: selectableKeys.length > 0 && selectableKeys.every(key => selected.includes(key))
    function closePopup(): void {
        editor.close();
    }
    function selectAll(value: bool): void {
        confirm.cancel();
        selected = value ? selectableKeys.slice() : [];
    }
    function select(key: string, value: bool): void {
        confirm.cancel();
        const other = key === "mise-tools" ? "mise-unused" : key === "mise-unused" ? "mise-tools" : "";
        selected = selected.filter(item => item !== key && (!value || item !== other)).concat(value ? [key] : []);
    }
    onActiveChanged: if (!active)
        closePopup()
    objectName: "systemCleanup"
    iconName: "brush-cleaning"
    idleColor: Theme.surface
    highlighted: editor.visible || hovered || visualFocus
    text: service.cleaning ? qsTr("Cleaning system…") : qsTr("Clean system")
    onClicked: if (editor.visible)
        editor.close()
    else
        editor.open()
    Popup {
        id: editor
        objectName: "cleanupPopup"
        popupType: Popup.Item
        parent: root
        x: 0
        y: -height - 8
        width: root.width
        height: Math.min(620, implicitHeight, (Overlay.overlay?.height ?? 700) - 32)
        padding: 12
        margins: 8
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        background: Surface {
            color: Theme.background
            radius: Theme.controlRadius
        }
        onAboutToShow: {
            root.popupOpened();
            root.selected = [];
            root.service.scan();
        }
        onOpened: choices.forceActiveFocus()
        onClosed: {
            confirm.cancel();
            if (root.active)
                root.forceActiveFocus();
        }
        contentItem: ColumnLayout {
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                ShellText {
                    text: qsTr("Free up space")
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                ChoiceBox {
                    objectName: "cleanupSelectAll"
                    text: qsTr("Select all")
                    enabled: root.selectableKeys.length > 0 && !root.service.busy
                    checkState: root.allSelected ? Qt.Checked : root.selected.length ? Qt.PartiallyChecked : Qt.Unchecked
                    onClicked: root.selectAll(!root.allSelected)
                }
            }
            DrawerColumn {
                id: choices
                objectName: "cleanupChoices"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredHeight: 440
                Repeater {
                    model: root.service.entries
                    delegate: ColumnLayout {
                        id: choice
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        spacing: 3
                        ShellText {
                            visible: choice.index === 0 || root.service.entries[choice.index - 1].group !== choice.modelData.group
                            text: choice.modelData.group
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                            Layout.topMargin: choice.index ? 8 : 0
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            ChoiceBox {
                                objectName: "cleanup:" + choice.modelData.id
                                Layout.fillWidth: true
                                enabled: choice.modelData.available && !root.service.busy
                                checked: root.selected.includes(choice.modelData.id)
                                text: choice.modelData.title
                                onToggled: root.select(choice.modelData.id, checked)
                            }
                            IconButton {
                                objectName: "cleanupAdmin:" + choice.modelData.id
                                visible: choice.modelData.admin ?? false
                                iconName: "shield-lock"
                                text: qsTr("May require administrator approval")
                                implicitWidth: 24
                                implicitHeight: 24
                                padding: 4
                            }
                        }
                        Note {
                            visible: text !== ""
                            text: choice.modelData.detail
                            Layout.leftMargin: 26
                        }
                    }
                }
            }
            RowLayout {
                visible: root.service.busy
                Layout.fillWidth: true
                BusySpinner {
                    implicitWidth: 16
                    implicitHeight: 16
                }
                Note {
                    text: root.service.cleaning ? qsTr("Cleaning %1…").arg(root.service.progress) : qsTr("Finding cleanup options…")
                }
            }
            HoldButton {
                id: confirm
                objectName: "cleanupConfirm"
                Layout.fillWidth: true
                text: qsTr("Hold to clean · %1 selected").arg(root.selected.length)
                enabled: root.active && !root.service.busy && root.selected.length > 0
                armed: editor.visible
                onConfirmed: {
                    root.service.clean(root.selected.slice());
                    root.selected = [];
                }
            }
        }
    }
    component ChoiceBox: CheckBox {
        id: checkbox
        padding: 0
        spacing: 8
        implicitHeight: Math.max(24, contentItem.implicitHeight)
        opacity: enabled ? 1 : 0.45
        indicator: Rectangle {
            implicitWidth: 18
            implicitHeight: 18
            x: 0
            y: (checkbox.height - height) / 2
            radius: 3
            color: checkbox.checkState !== Qt.Unchecked ? Theme.accent : Theme.raised
            border.width: 1
            border.color: checkbox.visualFocus ? Theme.accent : Theme.border
            Icon {
                anchors.centerIn: parent
                width: 14
                height: 14
                name: "check"
                color: Theme.accentText
                visible: checkbox.checkState === Qt.Checked
            }
            Rectangle {
                anchors.centerIn: parent
                width: 10
                height: 2
                color: Theme.accentText
                visible: checkbox.checkState === Qt.PartiallyChecked
            }
        }
        contentItem: ShellText {
            text: checkbox.text
            leftPadding: 26
            wrapMode: Text.Wrap
            verticalAlignment: Text.AlignVCenter
            textFormat: Text.PlainText
        }
    }
    component Note: ShellText {
        Layout.fillWidth: true
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
}
