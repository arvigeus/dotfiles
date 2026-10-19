pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../ui"
import "audio"
import "network"
import "network/Models.js" as Models

DrawerPage {
    id: root
    property var service: AudioService
    property var audioTest: testService
    AudioTestService { id: testService }
    readonly property var inputs: service.state.inputs ?? []
    readonly property var devices: service.state.inputDevices ?? []
    readonly property var destinations: inputs.filter(input => input.available && (!input.routes.length || input.routes.some(route => route.selected)))
    readonly property bool canAct: active && service.state.available
    headerActions: AudioIconButton {
        iconName: "pencil"; text: qsTr("Advanced microphone settings")
        onClicked: { Quickshell.execDetached(["pavucontrol-qt", "--tab=4"]); root.closeRequested(); }
    }
    ListModel { id: devicesModel; dynamicRoles: true }
    ListModel { id: recordingsModel; dynamicRoles: true }
    function syncModels(): void {
        Models.sync(devicesModel, devices.filter(device => device.available), "key", false);
        Models.sync(recordingsModel, service.state.recordings ?? [], "key", false);
    }
    Connections { target: root.service; function onStateChanged(): void { root.syncModels(); } }
    onActiveChanged: { service.observe(root, active); if (!active) audioTest.cancel(); }
    Component.onCompleted: { syncModels(); service.observe(root, active); }
    Component.onDestruction: { service.observe(root, false); audioTest.cancel(); }
    function recordingAction(op, recording, values = {}): void {
        service.run(op, Object.assign({kind: "recording", index: recording.index, token: recording.token}, values));
    }
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
        AudioIconButton {
            objectName: "inputDefault:" + title.record.key
            iconName: "check"; text: qsTr("Use %1 as the default microphone").arg(title.record.label)
            checked: title.live && title.record.selected; iconColor: checked ? Theme.accent : Theme.muted
            highlightChecked: false
            Accessible.checkable: true; Accessible.checked: checked
            enabled: title.live && root.canAct && !root.service.busy && root.destinations.some(node => node.name === title.record.name)
            onClicked: root.service.run("input-default", {name: title.record.name})
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
        required property var record
        required property var deviceRecord
        objectName: "audioInput:" + record.key
        Layout.fillWidth: true; spacing: 4
        ListModel { id: routesModel; dynamicRoles: true }
        onRecordChanged: Models.sync(routesModel, record.routes, "name", false)
        Component.onCompleted: Models.sync(routesModel, record.routes, "name", false)
        InputTitle { record: input.record; live: input.record.live }
        Note {
            objectName: "inputState:" + input.record.key
            visible: text !== ""
            text: !input.record.live && input.deviceRecord.enabled ? qsTr("Input unavailable")
                : input.record.live && !input.record.muted && root.service.state.recordings?.some(app => app.source === input.record.index && app.recording && !app.muted) ? qsTr("In use") : ""
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            VolumeControl {
                objectName: "inputVolume:" + input.record.key; Layout.fillWidth: true
                enabled: root.canAct; microphone: true; maximum: 100; showPercentage: false
                label: input.record.label; volume: input.record.volume; muted: !input.record.live || input.record.muted
                canVolume: input.record.live && input.deviceRecord.enabled && !input.record.muted
                canMute: input.record.live && input.deviceRecord.enabled && !root.service.busy
                muteHint: input.record.muted ? qsTr("Unmute %1").arg(input.record.label) : qsTr("Mute %1").arg(input.record.label)
                onMuteClicked: root.service.run("mute", {kind: "source", name: input.record.name, muted: !input.record.muted})
                onVolumeEdited: value => root.service.run("volume", {kind: "source", name: input.record.name, value})
            }
        }
        NetworkChoice {
            id: connection
            objectName: "inputConnection:" + input.record.key; Layout.fillWidth: true
            visible: routesModel.count > 1 || (routesModel.count > 0 && !input.record.routes.some(route => route.selected))
            enabled: input.record.live && root.canAct && !root.service.busy
            Accessible.name: qsTr("Connection for %1").arg(input.record.label)
            model: routesModel; textRole: "identity"
            delegate: ItemDelegate {
                required property var record
                required property int index
                width: connection.popup.width
                text: record.label
                highlighted: index === connection.highlightedIndex
                palette.text: Theme.text; palette.highlightedText: Theme.text
            }
            displayText: input.record.routes.find(route => route.selected)?.label ?? qsTr("Choose a connection")
            currentIndex: input.record.routes.findIndex(route => route.selected)
            onActivated: index => {
                const port = routesModel.get(index).record.name;
                currentIndex = Qt.binding(() => input.record.routes.findIndex(route => route.selected));
                root.service.run("input-port", {name: input.record.name, port});
            }
        }
    }
    component InputDevice: Surface {
        id: device
        required property var record
        readonly property var sources: root.inputs.filter(input => input.deviceKey === record.key && input.available)
        property var lastSources: []
        readonly property var displaySources: {
            if (sources.length) return sources.map(source => Object.assign({}, source, {live: true}));
            const slots = lastSources.length ? lastSources : record.inputSlots ?? [{key: record.key + "/input", label: record.label, routes: []}];
            return slots.map(source => Object.assign({name: "", index: -1, volume: 0, muted: true, routes: []}, source, {live: false, selected: false}));
        }
        objectName: "inputDevice:" + record.key
        Layout.fillWidth: true; implicitHeight: content.implicitHeight + 24
        color: Theme.surface; border.width: 0; radius: Theme.controlRadius
        ListModel { id: sourcesModel; dynamicRoles: true }
        onSourcesChanged: { if (sources.length) lastSources = sources; }
        onDisplaySourcesChanged: Models.sync(sourcesModel, displaySources, "key", false)
        Component.onCompleted: {
            if (sources.length) lastSources = sources;
            Models.sync(sourcesModel, displaySources, "key", false);
        }
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
            AudioIconButton { iconName: "refresh-cw"; text: qsTr("Refresh microphones"); onClicked: root.service.refresh() }
            AudioIconButton { iconName: "x"; text: qsTr("Dismiss microphone error"); onClicked: root.service.error = "" }
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
            Note { objectName: "microphoneInputsEmpty"; visible: root.service.loaded && !devicesModel.count; text: qsTr("No microphones connected.") }
            Repeater { model: devicesModel; delegate: InputDevice {} }
            Heading { text: qsTr("Applications"); Layout.topMargin: 8 }
            Note { objectName: "recordingAppsEmpty"; visible: root.service.loaded && !recordingsModel.count; text: qsTr("No applications are using a microphone.") }
            Repeater {
                model: recordingsModel
                delegate: ColumnLayout {
                    id: app
                    required property var record
                    objectName: "recordingApp:" + record.key
                    Layout.fillWidth: true; spacing: 4
                    RowLayout {
                        Layout.fillWidth: true; spacing: 10
                        AppIcon { visible: app.record.icon !== ""; icon: app.record.icon; Layout.preferredWidth: 20; Layout.preferredHeight: 20 }
                        ShellText { text: app.record.label; Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText }
                        Note { Layout.fillWidth: false; text: app.record.muted || root.inputs.some(input => input.index === app.record.source && input.muted)
                            ? qsTr("Muted") : app.record.recording ? qsTr("Recording") : qsTr("Paused") }
                    }
                    NetworkChoice {
                        id: appInput
                        objectName: "recordingInput:" + app.record.key; Layout.fillWidth: true
                        enabled: root.canAct && !root.service.busy && root.destinations.length > 0
                        Accessible.name: qsTr("Microphone for %1").arg(app.record.label)
                        model: root.destinations; textRole: "label"
                        currentIndex: root.destinations.findIndex(input => input.index === app.record.source)
                        displayText: root.destinations.find(input => input.index === app.record.source)?.label ?? qsTr("Input unavailable")
                        onActivated: index => {
                            const destination = root.destinations[index].name;
                            currentIndex = Qt.binding(() => root.destinations.findIndex(input => input.index === app.record.source));
                            root.recordingAction("move", app.record, {destination});
                        }
                    }
                }
            }
        }
        AudioTestButton {
            objectName: "microphoneTestButton"; Layout.fillWidth: true
            microphone: true; tester: root.audioTest
            readonly property var input: root.destinations.find(node => node.selected)
            readonly property var output: (root.service.state.outputs ?? []).find(node => node.selected && node.available && (!node.routes.length || node.routes.some(route => route.selected)))
            canStart: root.canAct && !root.service.busy && !!input && !input.muted && !!output && !output.muted
            targetLabel: [input?.label, output?.label].filter(label => label).join(" → ")
        }
    }
}
