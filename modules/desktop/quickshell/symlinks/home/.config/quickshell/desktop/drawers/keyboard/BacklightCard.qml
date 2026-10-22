pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../../ui"

Surface {
    id: root
    required property var record
    required property var service
    property bool active: false
    readonly property alias menu: options
    readonly property var effects: record.effects || []
    readonly property var modes: record.modes || []
    readonly property bool hasOptions: effects.length > 0 || modes.length > 1
    readonly property string title: record.connection || record.label || qsTr("Keyboard")
    signal optionsOpened(var menu)
    signal optionsClosed(var menu)
    objectName: "keyboardCard:" + record.key
    implicitHeight: content.implicitHeight + 24
    color: Theme.surface; border.width: 0; radius: Theme.controlRadius
    onHasOptionsChanged: if (!hasOptions) options.close()
    onActiveChanged: if (!active) options.close()
    Component.onDestruction: if (options.visible) optionsClosed(options)
    ColumnLayout {
        id: content
        anchors.fill: parent; anchors.margins: 12; spacing: 8
        ShellText { text: root.title; Layout.fillWidth: true; elide: Text.ElideRight; font.weight: Font.DemiBold }
        ShellText { visible: (root.record.label || "") !== root.title; text: root.record.label || ""; Layout.fillWidth: true; elide: Text.ElideRight }
        ShellText {
            Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.smallFontSize; wrapMode: Text.Wrap
            text: root.record.mode === 1 ? qsTr("Automatic brightness")
                : root.record.mode === 255 || root.record.value === 0 ? qsTr("Backlight off")
                : root.effects.find(item => item.id === root.record.effect)?.label
                    || (root.record.mode === 3 ? qsTr("Manual brightness") : qsTr("Backlight brightness"))
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            Icon { name: "sun"; color: Theme.muted; Layout.preferredWidth: 20; Layout.preferredHeight: 20 }
            BacklightControl {
                Layout.fillWidth: true; record: root.record; active: root.active
                onEdited: value => root.service.setBrightness(root.record, value)
            }
            IconButton {
                id: cog
                objectName: "keyboardOptions:" + root.record.key
                iconName: "settings"; text: qsTr("Lighting for %1").arg(root.title)
                visible: root.hasOptions
                enabled: root.active && root.record.available
                onClicked: options.visible ? options.close() : options.open()
            }
        }
    }
    component Option: Button {
        id: button
        property bool marked: false
        Layout.fillWidth: true; implicitHeight: 36; padding: 8; hoverEnabled: true
        contentItem: RowLayout {
            spacing: 8
            Icon { name: "check"; opacity: button.marked ? 1 : 0; Layout.preferredWidth: 16; Layout.preferredHeight: 16 }
            ShellText { text: button.text; Layout.fillWidth: true; elide: Text.ElideRight }
        }
        background: ButtonBackground { highlighted: button.hovered || button.visualFocus; pressed: button.down }
    }
    component Heading: ShellText {
        Layout.fillWidth: true; font.weight: Font.DemiBold; font.pixelSize: Theme.smallFontSize
    }
    Popup {
        id: options
        objectName: "keyboardLighting:" + root.record.key
        parent: cog; popupType: Popup.Item
        x: cog.width - width; y: cog.height
        width: Math.min(300, root.width); padding: 8; margins: 8; focus: true
        height: Math.max(0, Math.min(form.contentHeight + topPadding + bottomPadding, 560, (Overlay.overlay?.height ?? 600) - 16))
        closePolicy: Popup.CloseOnPressOutsideParent | Popup.CloseOnEscape
        onAboutToShow: root.optionsOpened(options)
        onClosed: root.optionsClosed(options)
        background: Surface { color: Theme.background; radius: Theme.controlRadius }
        contentItem: DrawerColumn {
            id: form
            Keys.onEscapePressed: event => { options.close(); event.accepted = true; }
            ColumnLayout {
                visible: root.effects.length > 0
                Layout.fillWidth: true; spacing: 2
                Heading { text: qsTr("Effect") }
                Repeater {
                    model: KeyedModel { values: root.effects; keyField: "id" }
                    delegate: Option {
                        required property var modelData
                        readonly property var record: modelData
                        objectName: "keyboardEffect:" + record.id
                        text: record.label; marked: root.record.effect === record.id
                        onClicked: { root.service.setEffect(root.record, record.id); options.close(); }
                    }
                }
            }
            ColumnLayout {
                objectName: "keyboardColors"
                visible: root.record.rgb === true
                Layout.fillWidth: true; spacing: 8
                Heading { text: qsTr("Color") }
                GridLayout {
                    Layout.fillWidth: true; columns: 4; columnSpacing: 8; rowSpacing: 4
                    Repeater {
                        model: [{color:"#ffffff",name:qsTr("White")},{color:"#ff0000",name:qsTr("Red")},
                            {color:"#ff8000",name:qsTr("Orange")},{color:"#ffff00",name:qsTr("Yellow")},
                            {color:"#00ff00",name:qsTr("Green")},{color:"#00ffff",name:qsTr("Cyan")},
                            {color:"#0080ff",name:qsTr("Blue")},{color:"#8000ff",name:qsTr("Purple")}]
                        delegate: Button {
                            id: swatch
                            required property var modelData
                            objectName: "keyboardColor:" + modelData.color
                            Layout.fillWidth: true; implicitHeight: 36; padding: 4; hoverEnabled: true
                            text: modelData.name; Accessible.name: text
                            contentItem: Item {
                                Rectangle {
                                    anchors.centerIn: parent; width: 24; height: 24; radius: 12; color: swatch.modelData.color
                                    border.width: 1; border.color: Theme.border
                                    Icon {
                                        anchors.centerIn: parent; width: 16; height: 16; name: "check"
                                        visible: root.record.color === swatch.modelData.color
                                        color: ["#0080ff", "#8000ff", "#ff0000"].includes(swatch.modelData.color) ? "white" : "black"
                                    }
                                }
                            }
                            background: ButtonBackground { highlighted: swatch.hovered || swatch.visualFocus; pressed: swatch.down }
                            PassiveToolTip { target: swatch }
                            onClicked: { root.service.setColor(root.record, modelData.color); options.close(); }
                        }
                    }
                }
            }
            ColumnLayout {
                visible: root.modes.length > 1
                Layout.fillWidth: true; spacing: 2
                Heading { text: qsTr("Backlight mode") }
                Repeater {
                    model: KeyedModel { values: root.modes; keyField: "id" }
                    delegate: Option {
                        required property var modelData
                        readonly property var record: modelData
                        objectName: "keyboardMode:" + record.id
                        text: record.label; marked: root.record.mode === record.id
                        onClicked: { root.service.setMode(root.record, record.id); options.close(); }
                    }
                }
            }
        }
    }
}
