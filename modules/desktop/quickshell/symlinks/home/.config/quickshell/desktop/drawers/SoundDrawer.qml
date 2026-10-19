pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQml.Models
import Quickshell
import Quickshell.Services.Mpris
import "../ui"
import "audio"
import "network"
import "network/Models.js" as Models

DrawerPage {
    id: root
    property var service: AudioService
    property var audioTest: testService
    AudioTestService { id: testService }
    readonly property var outputs: service.state.outputs ?? []
    readonly property var devices: service.state.outputDevices ?? []
    readonly property var destinations: outputs.filter(output => output.available && (!output.routes.length || output.routes.some(route => route.selected)))
    readonly property bool canAct: active && service.state.available
    property var players: Mpris.players.values.filter(player => player.dbusName !== "org.mpris.MediaPlayer2.playerctld")
    // A transport controls a media session, whereas a mixer row controls an audio
    // stream. Associate them only when application identity gives a unique pair.
    readonly property var playerAssignments: {
        const streams = service.state.streams ?? [];
        const matches = players.map(player => {
            const candidates = streams.filter(stream => playerMatchesStream(player, stream));
            return {player, key: candidates.length === 1 ? candidates[0].key : ""};
        });
        return matches.map(match => ({player: match.player, key: match.key && matches.filter(other => other.key === match.key).length === 1 ? match.key : ""}));
    }
    function playerMatchesStream(player, stream): bool {
        const normalize = value => String(value ?? "").trim().toLowerCase().replace(/\.desktop$/, "");
        const desktop = normalize(player.desktopEntry);
        if (desktop) {
            if (stream.applicationId) return desktop === normalize(stream.applicationId);
            return [stream.applicationBinary, stream.icon].some(value => value && desktop === normalize(value));
        }
        return normalize(player.identity) !== "" && normalize(player.identity) === normalize(stream.label);
    }
    headerActions: AudioIconButton {
        objectName: "audioSettings"; iconName: "pencil"; text: qsTr("Advanced sound settings")
        onClicked: { Quickshell.execDetached(["pavucontrol-qt"]); root.closeRequested(); }
    }
    ListModel { id: devicesModel; dynamicRoles: true }
    ListModel { id: appsModel; dynamicRoles: true }
    function syncModels(): void {
        Models.sync(devicesModel, devices.filter(device => device.available), "key", false);
        Models.sync(appsModel, service.state.streams ?? [], "key", false);
    }
    Connections { target: root.service; function onStateChanged(): void { root.syncModels(); } }
    onActiveChanged: { service.observe(root, active); if (!active) audioTest.cancel(); }
    Component.onCompleted: { syncModels(); service.observe(root, active); }
    Component.onDestruction: { service.observe(root, false); audioTest.cancel(); }
    function streamAction(op, stream, values = {}): void {
        service.run(op, Object.assign({kind: "stream", index: stream.index, token: stream.token}, values));
    }
    function boostForSink(index: int): bool { return service.boostFor(outputs.find(output => output.index === index)?.deviceKey ?? ""); }
    function boostPendingForSink(index: int): bool { return service.boostPending(outputs.find(output => output.index === index)?.deviceKey ?? ""); }
    component Note: ShellText {
        Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap; textFormat: Text.PlainText
    }
    component Heading: ShellText { Layout.fillWidth: true; font.weight: Font.DemiBold; textFormat: Text.PlainText }
    component OutputControl: ColumnLayout {
        id: output
        required property var record
        objectName: "audioOutput:" + record.key
        Layout.fillWidth: true; spacing: 4
        ListModel { id: routesModel; dynamicRoles: true }
        onRecordChanged: Models.sync(routesModel, record.routes, "name", false)
        Component.onCompleted: Models.sync(routesModel, record.routes, "name", false)
        RowLayout {
            Layout.fillWidth: true
            ShellText { text: output.record.label; Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText }
            AudioIconButton {
                objectName: "outputDefault:" + output.record.key
                iconName: "check"; text: qsTr("Use %1 as the default output").arg(output.record.label)
                checked: output.record.selected; iconColor: checked ? Theme.accent : Theme.muted
                highlightChecked: false
                Accessible.checkable: true; Accessible.checked: checked
                enabled: root.canAct && !root.service.busy && root.destinations.some(node => node.name === output.record.name)
                onClicked: root.service.run("output-default", {name: output.record.name})
            }
        }
        Note {
            objectName: "outputState:" + output.record.key
            text: output.record.muted ? qsTr("Muted") : output.record.portLabel || qsTr("Ready")
        }
        VolumeControl {
            objectName: "outputVolume:" + output.record.key; Layout.fillWidth: true
            enabled: root.canAct; label: output.record.label; showPercentage: false
            volume: output.record.volume; muted: output.record.muted
            canVolume: !output.record.muted && !root.service.boostPending(output.record.deviceKey); canMute: !root.service.busy
            maximum: Math.min(output.record.maxVolume, root.service.boostFor(output.record.deviceKey) ? 150 : 100)
            onVolumeEdited: value => root.service.run("volume", {name: output.record.name, value, boost: root.service.boostFor(output.record.deviceKey)})
            onMuteClicked: root.service.run("mute", {name: output.record.name, muted: !output.record.muted})
        }
        NetworkChoice {
            id: connection
            objectName: "outputConnection:" + output.record.key; Layout.fillWidth: true
            visible: routesModel.count > 1 || (routesModel.count > 0 && !output.record.routes.some(route => route.selected))
            enabled: root.canAct && !root.service.busy
            Accessible.name: qsTr("Connection for %1").arg(output.record.label)
            model: routesModel; textRole: "identity"
            delegate: ItemDelegate {
                required property var record
                required property int index
                width: connection.popup.width; text: record.label
                highlighted: index === connection.highlightedIndex
                palette.text: Theme.text; palette.highlightedText: Theme.text
            }
            displayText: output.record.routes.find(route => route.selected)?.label ?? qsTr("Choose a connection")
            currentIndex: output.record.routes.findIndex(route => route.selected)
            onActivated: index => {
                const port = routesModel.get(index).record.name;
                currentIndex = Qt.binding(() => output.record.routes.findIndex(route => route.selected));
                root.service.run("output-port", {name: output.record.name, port, boost: root.service.boostFor(output.record.deviceKey)});
            }
        }
    }
    component OutputDevice: Surface {
        id: device
        required property var record
        readonly property var sinks: root.outputs.filter(output => output.deviceKey === record.key && output.available)
        objectName: "outputDevice:" + record.key
        Layout.fillWidth: true; implicitHeight: content.implicitHeight + 24
        color: Theme.surface; border.width: 0; radius: Theme.controlRadius
        ListModel { id: sinksModel; dynamicRoles: true }
        onSinksChanged: Models.sync(sinksModel, sinks, "key", false)
        Component.onCompleted: Models.sync(sinksModel, sinks, "key", false)
        ColumnLayout {
            id: content
            anchors.fill: parent; anchors.margins: 12; spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Heading { text: device.record.label; wrapMode: Text.Wrap }
                AudioIconButton {
                    id: settings
                    readonly property alias menu: options
                    objectName: "outputOptions:" + device.record.key
                    iconName: "settings"; text: qsTr("Playback options for %1").arg(device.record.label)
                    enabled: root.canAct && !root.service.busy
                    onClicked: options.open()
                    Menu {
                        id: options
                        popupType: Popup.Item
                        x: settings.width - width; y: settings.height
                        width: Math.min(320, root.width); padding: 6
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                        background: Surface { color: Theme.background; radius: Theme.controlRadius }
                        Instantiator {
                            model: device.record.profiles.filter(mode => mode.enabled || mode.selected)
                            delegate: NetworkMenuItem {
                                id: profileOption
                                required property var modelData
                                objectName: "audioProfile:" + device.record.key + ":" + modelData.name
                                text: modelData.label; marked: modelData.selected
                                Accessible.checkable: true; Accessible.checked: marked
                                enabled: root.canAct && !root.service.busy && modelData.enabled
                                onTriggered: root.service.run("profile", {card: device.record.card, previous: device.record.profile, profile: modelData.name})
                                PassiveToolTip { target: profileOption; text: profileOption.modelData.reason || profileOption.modelData.description || profileOption.modelData.label }
                            }
                            onObjectAdded: (index, item) => options.insertItem(index, item)
                            onObjectRemoved: (index, item) => options.removeItem(item)
                        }
                        // Add the footer explicitly: static Menu children can be
                        // interleaved with Instantiator insertions during startup.
                        property MenuSeparator separator: MenuSeparator {
                            objectName: "outputOptionsSeparator:" + device.record.key
                            visible: device.record.profiles.some(mode => mode.enabled || mode.selected)
                            padding: 6; contentItem: Rectangle { implicitHeight: 1; color: Theme.border }
                        }
                        property NetworkMenuItem boostItem: NetworkMenuItem {
                            objectName: "audioBoost:" + device.record.key; text: qsTr("Boost audio")
                            marked: root.service.boostFor(device.record.key)
                            Accessible.checkable: true; Accessible.checked: marked
                            enabled: root.canAct && !root.service.busy
                            onTriggered: root.service.setBoost(device.record.key, !marked)
                        }
                        Component.onCompleted: { addItem(separator); addItem(boostItem); }
                    }
                    Connections { target: root; function onActiveChanged(): void { if (!root.active) options.close(); } }
                }
            }
            Repeater { model: sinksModel; delegate: OutputControl {} }
        }
    }
    ColumnLayout {
        anchors.fill: parent; spacing: 8
        RowLayout {
            visible: root.service.error !== ""; Layout.fillWidth: true
            Note { objectName: "audioError"; text: root.service.error; color: Theme.danger }
            AudioIconButton { iconName: "refresh-cw"; text: qsTr("Refresh audio devices"); onClicked: root.service.refresh() }
            AudioIconButton { iconName: "x"; text: qsTr("Dismiss audio error"); onClicked: root.service.error = "" }
        }
        Note { visible: root.service.state.warning !== ""; text: root.service.state.warning; color: Theme.warning }
        RowLayout {
            visible: !root.service.loaded
            BusySpinner { implicitWidth: 16; implicitHeight: 16 }
            Note { text: qsTr("Loading audio devices…") }
        }
        DrawerColumn {
            objectName: "audioScroll"; Layout.fillWidth: true; Layout.fillHeight: true
            Heading { text: qsTr("Outputs") }
            Note { objectName: "audioOutputsEmpty"; visible: root.service.loaded && !devicesModel.count; text: qsTr("No playback devices available.") }
            Repeater { model: devicesModel; delegate: OutputDevice {} }
            Heading { text: qsTr("Applications"); Layout.topMargin: 8 }
            Note { objectName: "audioAppsEmpty"; visible: root.service.loaded && !appsModel.count; text: qsTr("No applications are using audio.") }
            Repeater {
                model: appsModel
                delegate: ColumnLayout {
                    id: app
                    required property var record
                    objectName: "audioApp:" + record.key
                    Layout.fillWidth: true; spacing: 4
                    RowLayout {
                        Layout.fillWidth: true; spacing: 10
                        AppIcon { visible: app.record.icon !== ""; icon: app.record.icon; Layout.preferredWidth: 20; Layout.preferredHeight: 20 }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 1
                            ShellText { text: app.record.label; Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText }
                            Note { visible: app.record.detail !== "" && app.record.detail !== app.record.label && app.record.detail !== "AudioStream"; text: app.record.detail; maximumLineCount: 1; elide: Text.ElideRight }
                        }
                        Note { visible: app.record.muted; text: qsTr("Muted"); Layout.fillWidth: false }
                    }
                    MediaControls {
                        objectName: "appPlayback:" + app.record.key
                        Layout.fillWidth: true; active: root.active
                        players: root.playerAssignments.filter(match => match.key === app.record.key).map(match => match.player)
                    }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        VolumeControl {
                            objectName: "appVolume:" + app.record.key; Layout.fillWidth: true
                            enabled: root.canAct; label: app.record.label
                            volume: app.record.volume; muted: app.record.muted; showPercentage: false
                            canVolume: app.record.hasVolume && app.record.canVolume && !app.record.muted && !root.boostPendingForSink(app.record.sink)
                            canMute: !root.service.busy
                            maximum: root.boostForSink(app.record.sink) ? 150 : 100
                            onVolumeEdited: value => root.streamAction("volume", app.record, {value, boost: root.boostForSink(app.record.sink)})
                            onMuteClicked: root.streamAction("mute", app.record, {muted: !app.record.muted})
                        }
                        AudioIconButton {
                            id: appSettings
                            readonly property alias menu: routeMenu
                            objectName: "appOptions:" + app.record.key
                            iconName: "settings"; text: qsTr("Output for %1").arg(app.record.label)
                            hint: text + "\n" + (root.destinations.find(o => o.index === app.record.sink)?.label ?? qsTr("Output unavailable"))
                            enabled: root.canAct && !root.service.busy && root.destinations.length > 0
                            onClicked: routeMenu.open()
                            Menu {
                                id: routeMenu
                                popupType: Popup.Item
                                x: appSettings.width - width; y: appSettings.height
                                width: Math.min(320, root.width); padding: 6
                                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                                background: Surface { color: Theme.background; radius: Theme.controlRadius }
                                Instantiator {
                                    model: root.destinations
                                    delegate: NetworkMenuItem {
                                        required property var modelData
                                        objectName: "appOutput:" + app.record.key + ":" + modelData.key
                                        text: modelData.label; marked: modelData.index === app.record.sink
                                        Accessible.checkable: true; Accessible.checked: marked
                                        enabled: root.canAct && !root.service.busy
                                        onTriggered: root.streamAction("move", app.record, {destination: modelData.name, boost: root.service.boostFor(modelData.deviceKey)})
                                    }
                                    onObjectAdded: (index, item) => routeMenu.insertItem(index, item)
                                    onObjectRemoved: (index, item) => routeMenu.removeItem(item)
                                }
                                Connections { target: root; function onActiveChanged(): void { if (!root.active) routeMenu.close(); } }
                            }
                        }
                    }
                }
            }
            MediaControls {
                objectName: "audioPlayback"; Layout.fillWidth: true; active: root.active; showHeading: true
                players: root.playerAssignments.filter(match => !match.key).map(match => match.player)
            }
        }
        AudioTestButton {
            objectName: "speakerTestButton"; Layout.fillWidth: true
            tester: root.audioTest
            canStart: root.canAct && !root.service.busy && root.destinations.some(node => !node.muted)
        }
    }
}
