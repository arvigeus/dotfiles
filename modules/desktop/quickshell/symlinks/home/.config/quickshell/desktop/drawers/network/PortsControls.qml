pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

ColumnLayout {
    id: root
    property var service: PortsService
    property bool active: false
    property string interfaceName: ""
    property bool connected: false
    readonly property bool popupOpen: editor.visible
    readonly property var ports: service.ports.filter(port => port.interface === root.interfaceName)
    readonly property bool canEdit: active && connected && service.available && !service.busy
    signal popupOpened()
    spacing: 8
    function closePopup(): void { editor.close(); }
    function alreadyOpen(port): bool { return ports.some(entry => entry.port === port); }
    onActiveChanged: { service.observing = active; if (!active) closePopup(); }
    onInterfaceNameChanged: closePopup()
    onConnectedChanged: if (!connected) closePopup()
    Component.onCompleted: service.observing = active
    Component.onDestruction: service.observing = false
    Connections {
        target: root.service
        function onCompleted(operation, success): void { if (operation === "open" && success) editor.close(); }
    }
    ShellText { text: qsTr("Ports"); font.weight: Font.DemiBold; Layout.fillWidth: true }
    Repeater {
        model: root.ports
        delegate: Surface {
            id: card
            required property var modelData
            objectName: "portCard:" + modelData.port
            Layout.fillWidth: true; implicitHeight: row.implicitHeight + 20
            color: Theme.surface; radius: Theme.controlRadius; border.width: 0
            RowLayout {
                id: row; anchors.fill: parent; anchors.margins: 10; spacing: 8
                ShellText { text: String(card.modelData.port); font.family: Theme.monospaceFamily }
                ShellText { text: qsTr("TCP"); color: Theme.muted; font.pixelSize: Theme.smallFontSize; Layout.fillWidth: true }
                IconButton {
                    objectName: "portClose:" + card.modelData.port
                    iconName: "x"; text: qsTr("Close")
                    enabled: root.active && !root.service.busy
                    Accessible.name: qsTr("Close port %1").arg(card.modelData.port)
                    onClicked: root.service.run("close", {interface: card.modelData.interface, port: card.modelData.port})
                }
            }
        }
    }
    ShellText {
        visible: root.service.error !== ""; text: root.service.error
        Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.danger; font.pixelSize: Theme.smallFontSize
    }
    ShellButton {
        id: add
        objectName: "portAdd"; text: qsTr("Open port"); Layout.fillWidth: true
        enabled: root.canEdit; checked: editor.visible
        PassiveToolTip { target: add; text: qsTr("Open a TCP/IPv4 port on %1 for its local network.").arg(root.interfaceName) }
        onClicked: { if (editor.visible) editor.close(); else editor.open(); }
        Popup {
            id: editor
            objectName: "portPopup"; parent: add; popupType: Popup.Item
            x: 0; y: add.height + 8; width: add.width; padding: 16; margins: 8; focus: true
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
            background: Surface { color: Theme.background; radius: Theme.controlRadius }
            onAboutToShow: root.popupOpened()
            onOpened: portNumber.focusEditor()
            onClosed: if (root.active) add.forceActiveFocus()
            contentItem: ColumnLayout {
                spacing: 12
                ShellText { text: qsTr("Port"); color: Theme.muted; font.pixelSize: Theme.smallFontSize }
                NumberField {
                    id: portNumber
                    objectName: "portNumber"; Layout.fillWidth: true
                    from: 1; to: 65535; value: 8080; Accessible.name: qsTr("Port")
                    onAccepted: if (open.enabled) open.clicked()
                }
                GridLayout {
                    Layout.fillWidth: true; columns: 3; columnSpacing: 6; rowSpacing: 6
                    Repeater {
                        model: [3000, 4321, 5173, 8000, 8080, 9000]
                        delegate: ShellButton {
                            required property int modelData
                            objectName: "portPreset:" + modelData
                            text: String(modelData); Layout.fillWidth: true
                            enabled: !root.alreadyOpen(modelData) && !root.service.busy
                            onClicked: { portNumber.value = modelData; portNumber.focusEditor(); }
                        }
                    }
                }
                ShellText {
                    visible: root.alreadyOpen(portNumber.number); text: qsTr("This port is already open.")
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.smallFontSize
                }
                ShellButton {
                    id: open
                    objectName: "portOpen"; text: qsTr("Open"); Layout.fillWidth: true
                    enabled: root.canEdit && portNumber.acceptableInput && !root.alreadyOpen(portNumber.number)
                    onClicked: root.service.run("open", {interface: root.interfaceName, port: portNumber.number})
                }
            }
        }
    }
}
