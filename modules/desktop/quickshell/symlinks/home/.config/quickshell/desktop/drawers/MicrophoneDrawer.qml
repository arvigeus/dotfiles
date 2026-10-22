pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../ui"
import "audio"

DrawerPage {
    id: root
    property var service: AudioService
    property var audioTest: testService
    AudioTestService { id: testService }
    readonly property var inputs: service.state.inputs ?? []
    readonly property var devices: service.state.inputDevices ?? []
    readonly property var destinations: inputs.filter(input => input.available && (!input.routes.length || input.routes.some(route => route.selected)))
    readonly property var recordings: service.recordings ?? []
    readonly property bool canAct: active && service.state.available
    headerActions: IconButton {
        iconName: "pencil"; text: qsTr("Advanced microphone settings")
        onClicked: { Apps.launch(["pavucontrol-qt", "--tab=4"]); root.closeRequested(); }
    }
    KeyedModel { id: devicesModel; values: root.devices.filter(device => device.available); keyField: "key" }
    KeyedModel { id: recordingsModel; values: root.recordings; keyField: "key" }
    onActiveChanged: { service.observe(root, active); if (!active) audioTest.cancel(); }
    Component.onCompleted: service.observe(root, active)
    Component.onDestruction: { service.observe(root, false); audioTest.cancel(); }
    function muted(name: string): bool { return service.nodes[name]?.audio?.muted ?? true; }
    component Note: ShellText {
        Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap; textFormat: Text.PlainText
    }
    component Heading: ShellText { Layout.fillWidth: true; font.weight: Font.DemiBold; textFormat: Text.PlainText }
    component InputTitle: RowLayout {
        id: title
        required property var record
        property bool live: true
        Layout.fillWidth: true
        ShellText { text: title.record.label; Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText }
        IconButton {
            objectName: "inputDefault:" + title.record.key
            iconName: "check"; text: qsTr("Use %1 as the default microphone").arg(title.record.label)
            checked: title.live && root.service.defaultSource === title.record.name; iconColor: checked ? Theme.accent : Theme.muted
            highlightChecked: false
            Accessible.checkable: true; Accessible.checked: checked
            enabled: title.live && root.canAct && !root.service.busy && root.destinations.some(node => node.name === title.record.name)
            onClicked: root.service.setDefault(root.service.nodes[title.record.name])
        }
    }
    component DeviceToggle: Switch {
        id: inputEnabled
        required property var record
        implicitWidth: 38
        Layout.preferredWidth: 38
        objectName: "inputEnabled:" + inputEnabled.record.key
        text: qsTr("Input enabled for %1").arg(record.label)
        Accessible.name: text
        checked: inputEnabled.record.enabled
        enabled: root.canAct && !root.service.busy && inputEnabled.record.canToggle
        hoverEnabled: true; spacing: 6; padding: 0; implicitHeight: Theme.controlHeight
        onToggled: {
            const requested = checked;
            checked = Qt.binding(() => inputEnabled.record.enabled);
            root.service.run("input-enabled", {card: inputEnabled.record.card, previous: inputEnabled.record.profile, port: inputEnabled.record.port, enabled: requested});
        }
        indicator: Rectangle {
            x: inputEnabled.width - width; y: (inputEnabled.height - height) / 2
            implicitWidth: 38; implicitHeight: 22; radius: height / 2
            color: inputEnabled.checked ? Theme.accent : Theme.border
            opacity: inputEnabled.enabled ? 1 : 0.45
            Rectangle {
                x: inputEnabled.checked ? parent.width - width - 3 : 3
                y: 3; width: 16; height: 16; radius: 8
                color: inputEnabled.checked ? Theme.accentText : Theme.text
            }
        }
        contentItem: Item {}
        background: ButtonBackground {
            idleColor: "transparent"; highlighted: inputEnabled.visualFocus; pressed: inputEnabled.down
        }
        PassiveToolTip {
            target: inputEnabled
            text: qsTr("Enable or disable all microphone inputs on %1. Playback mode is preserved.").arg(inputEnabled.record.label)
        }
    }
    component InputControl: ColumnLayout {
        id: input
        required property var modelData
        required property var deviceRecord
        readonly property var record: modelData
        readonly property var node: record.live ? root.service.nodes[record.name] ?? null : null
        readonly property bool live: !!node?.audio
        readonly property bool muted: node?.audio?.muted ?? true
        objectName: "audioInput:" + record.key
        Layout.fillWidth: true; spacing: 4
        KeyedModel { id: routesModel; values: input.record.routes; keyField: "name" }
        InputTitle { record: input.record; live: input.live }
        Note {
            objectName: "inputState:" + input.record.key
            visible: text !== ""
            text: !input.record.live && input.deviceRecord.enabled ? qsTr("Input unavailable")
                : input.live && !input.muted && root.recordings.some(app => app.target === input.record.name && app.active && !app.node?.audio?.muted) ? qsTr("In use") : ""
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            VolumeControl {
                objectName: "inputVolume:" + input.record.key; Layout.fillWidth: true
                enabled: root.canAct; microphone: true; maximum: 100; showPercentage: false
                label: input.record.label; volume: root.service.level(input.node); muted: input.muted
                canVolume: input.live && input.deviceRecord.enabled && !input.muted
                canMute: input.live && input.deviceRecord.enabled && !root.service.busy
                muteHint: input.muted ? qsTr("Unmute %1").arg(input.record.label) : qsTr("Mute %1").arg(input.record.label)
                onMuteClicked: root.service.setMuted(input.node, !input.muted)
                onVolumeEdited: value => root.service.setLevel(input.node, value)
            }
        }
        ShellChoice {
            id: connection
            objectName: "inputConnection:" + input.record.key; Layout.fillWidth: true
            visible: routesModel.values.length > 1 || (routesModel.values.length > 0 && !input.record.routes.some(route => route.selected))
            enabled: input.live && root.canAct && !root.service.busy
            Accessible.name: qsTr("Connection for %1").arg(input.record.label)
            model: routesModel; textRole: "modelData"
            delegate: ItemDelegate {
                required property var modelData
                required property int index
                width: connection.popup.width
                text: modelData.label
                highlighted: index === connection.highlightedIndex
                palette.text: Theme.text; palette.highlightedText: Theme.text
            }
            displayText: input.record.routes.find(route => route.selected)?.label ?? qsTr("Choose a connection")
            currentIndex: input.record.routes.findIndex(route => route.selected)
            onActivated: index => {
                const port = input.record.routes[index].name;
                currentIndex = Qt.binding(() => input.record.routes.findIndex(route => route.selected));
                root.service.run("input-port", {name: input.record.name, port});
            }
        }
    }
    component InputDevice: Card {
        id: device
        required property var modelData
        readonly property var record: modelData
        readonly property var sources: root.inputs.filter(input => input.deviceKey === record.key && input.available)
        property var lastSources: []
        readonly property var displaySources: {
            if (sources.length) return sources.map(source => Object.assign({}, source, {live: true}));
            const slots = lastSources.length ? lastSources : record.inputSlots ?? [{key: record.key + "/input", label: record.label, routes: []}];
            return slots.map(source => Object.assign({name: "", routes: []}, source, {live: false}));
        }
        objectName: "inputDevice:" + record.key
        Layout.fillWidth: true; implicitHeight: content.implicitHeight + 24
        KeyedModel { id: sourcesModel; values: device.displaySources; keyField: "key" }
        onSourcesChanged: { if (sources.length) lastSources = sources; }
        Component.onCompleted: { if (sources.length) lastSources = sources; }
        ColumnLayout {
            id: content
            anchors.fill: parent; anchors.margins: 12; spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Heading { text: device.record.label; wrapMode: Text.Wrap }
                DeviceToggle { record: device.record }
            }
            Note {
                objectName: "inputEnablementReason:" + device.record.key
                visible: !!device.record.toggleReason; text: device.record.toggleReason
            }
            Repeater {
                model: sourcesModel
                delegate: InputControl { deviceRecord: device.record }
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent; spacing: 8
        RowLayout {
            visible: root.service.error !== ""; Layout.fillWidth: true
            Note { objectName: "microphoneError"; text: root.service.error; color: Theme.danger }
            IconButton { iconName: "refresh-cw"; text: qsTr("Refresh microphones"); onClicked: root.service.refresh() }
            IconButton { iconName: "x"; text: qsTr("Dismiss microphone error"); onClicked: root.service.error = "" }
        }
        Note { visible: root.service.state.warning !== ""; text: root.service.state.warning; color: Theme.warning }
        RowLayout {
            visible: !root.service.loaded
            BusySpinner { implicitWidth: 16; implicitHeight: 16 }
            Note { text: qsTr("Loading microphones…") }
        }
        DrawerColumn {
            objectName: "microphoneScroll"; Layout.fillWidth: true; Layout.fillHeight: true
            Heading { text: qsTr("Inputs") }
            Note { objectName: "microphoneInputsEmpty"; visible: root.service.loaded && !devicesModel.values.length; text: qsTr("No microphones connected.") }
            Repeater { model: devicesModel; delegate: InputDevice {} }
            Heading { text: qsTr("Applications"); Layout.topMargin: 8 }
            Note { objectName: "recordingAppsEmpty"; visible: root.service.loaded && !recordingsModel.values.length; text: qsTr("No applications are using a microphone.") }
            Repeater {
                model: recordingsModel
                delegate: Card {
                    id: app
                    required property var modelData
                    readonly property var record: modelData
                    objectName: "recordingApp:" + record.key
                    Layout.fillWidth: true; implicitHeight: appContent.implicitHeight + 24
                    ColumnLayout {
                        id: appContent
                        anchors.fill: parent; anchors.margins: 12; spacing: 4
                        RowLayout {
                            Layout.fillWidth: true; spacing: 10
                            AppIcon { visible: app.record.icon !== ""; icon: app.record.icon; Layout.preferredWidth: 20; Layout.preferredHeight: 20 }
                            ShellText { text: app.record.label; Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText }
                            Note { Layout.fillWidth: false; text: (app.record.node?.audio?.muted ?? false) || (!!app.record.target && root.muted(app.record.target))
                                ? qsTr("Muted") : app.record.active ? qsTr("Recording") : qsTr("Paused") }
                        }
                        ShellChoice {
                            id: appInput
                            objectName: "recordingInput:" + app.record.key; Layout.fillWidth: true
                            enabled: root.canAct && !root.service.busy && root.destinations.length > 0
                            Accessible.name: qsTr("Microphone for %1").arg(app.record.label)
                            model: root.destinations; textRole: "label"
                            currentIndex: root.destinations.findIndex(input => input.name === app.record.target)
                            displayText: root.destinations.find(input => input.name === app.record.target)?.label ?? qsTr("Input unavailable")
                            onActivated: index => {
                                const destination = root.destinations[index];
                                currentIndex = Qt.binding(() => root.destinations.findIndex(input => input.name === app.record.target));
                                root.service.move(app.record, destination);
                            }
                        }
                    }
                }
            }
        }
        AudioTestButton {
            objectName: "microphoneTestButton"; Layout.fillWidth: true
            microphone: true; tester: root.audioTest
            readonly property var input: root.destinations.find(node => node.name === root.service.defaultSource)
            readonly property var output: (root.service.state.outputs ?? []).find(node => node.name === root.service.defaultSink && node.available && (!node.routes.length || node.routes.some(route => route.selected)))
            canStart: root.canAct && !root.service.busy && !!input && !root.muted(input.name) && !!output && !root.muted(output.name)
            targetLabel: [input?.label, output?.label].filter(label => label).join(" → ")
        }
    }
}
