pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQml.Models
import Quickshell
import Quickshell.Services.Mpris
import "../ui"
import "audio"

DrawerPage {
    id: root
    property var service: AudioService
    property var audioTest: testService
    AudioTestService { id: testService }
    readonly property var outputs: service.state.outputs ?? []
    readonly property var devices: service.state.outputDevices ?? []
    readonly property var destinations: outputs.filter(output => output.available && (!output.routes.length || output.routes.some(route => route.selected)))
    readonly property var streams: service.streams ?? []
    readonly property bool canAct: active && service.state.available
    property var players: Mpris.players.values.filter(player => player.dbusName !== "org.mpris.MediaPlayer2.playerctld")
    // A transport controls a media session, whereas a mixer row controls an audio
    // stream. Associate them only when application identity gives a unique pair.
    readonly property var playerAssignments: {
        const streams = root.streams;
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
    headerActions: IconButton {
        objectName: "audioSettings"; iconName: "pencil"; text: qsTr("Advanced sound settings")
        onClicked: { Apps.launch(["pavucontrol-qt"]); root.closeRequested(); }
    }
    ScriptModel { id: devicesModel; values: root.devices.filter(device => device.available); objectProp: "key" }
    ScriptModel { id: appsModel; values: root.streams; objectProp: "key" }
    onActiveChanged: { service.observe(root, active); if (!active) audioTest.cancel(); }
    Component.onCompleted: service.observe(root, active)
    Component.onDestruction: { service.observe(root, false); audioTest.cancel(); }
    function boostForSink(name: string): bool { return service.boostFor(outputs.find(output => output.name === name)?.deviceKey ?? ""); }
    function muted(name: string): bool { return service.nodes[name]?.audio?.muted ?? true; }
    component Note: ShellText {
        Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap; textFormat: Text.PlainText
    }
    component Heading: ShellText { Layout.fillWidth: true; font.weight: Font.DemiBold; textFormat: Text.PlainText }
    component OutputControl: ColumnLayout {
        id: output
        required property var modelData
        readonly property var record: modelData
        readonly property var node: root.service.nodes[record.name] ?? null
        readonly property bool muted: node?.audio?.muted ?? false
        objectName: "audioOutput:" + record.key
        Layout.fillWidth: true; spacing: 4
        ScriptModel { id: routesModel; values: output.record.routes; objectProp: "name" }
        RowLayout {
            Layout.fillWidth: true
            ShellText { text: output.record.label; Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText }
            IconButton {
                objectName: "outputDefault:" + output.record.key
                iconName: "check"; text: qsTr("Use %1 as the default output").arg(output.record.label)
                checked: root.service.defaultSink === output.record.name; iconColor: checked ? Theme.accent : Theme.muted
                highlightChecked: false
                Accessible.checkable: true; Accessible.checked: checked
                enabled: root.canAct && !root.service.busy && !!output.node && root.destinations.some(node => node.name === output.record.name)
                onClicked: root.service.setDefault(output.node)
            }
        }
        Note {
            objectName: "outputState:" + output.record.key
            text: output.muted ? qsTr("Muted") : output.record.portLabel || qsTr("Ready")
        }
        VolumeControl {
            objectName: "outputVolume:" + output.record.key; Layout.fillWidth: true
            enabled: root.canAct; label: output.record.label; showPercentage: false
            volume: root.service.level(output.node); muted: output.muted
            canVolume: !!output.node && !output.muted; canMute: !!output.node && !root.service.busy
            maximum: Math.min(output.record.maxVolume, root.service.boostFor(output.record.deviceKey) ? 150 : 100)
            onVolumeEdited: value => root.service.setLevel(output.node, value)
            onMuteClicked: root.service.setMuted(output.node, !output.muted)
        }
        ShellChoice {
            id: connection
            objectName: "outputConnection:" + output.record.key; Layout.fillWidth: true
            visible: routesModel.values.length > 1 || (routesModel.values.length > 0 && !output.record.routes.some(route => route.selected))
            enabled: root.canAct && !root.service.busy
            Accessible.name: qsTr("Connection for %1").arg(output.record.label)
            model: routesModel; textRole: "modelData"
            delegate: ItemDelegate {
                required property var modelData
                required property int index
                width: connection.popup.width; text: modelData.label
                highlighted: index === connection.highlightedIndex
                palette.text: Theme.text; palette.highlightedText: Theme.text
            }
            displayText: output.record.routes.find(route => route.selected)?.label ?? qsTr("Choose a connection")
            currentIndex: output.record.routes.findIndex(route => route.selected)
            onActivated: index => {
                const port = output.record.routes[index].name;
                currentIndex = Qt.binding(() => output.record.routes.findIndex(route => route.selected));
                root.service.run("output-port", {name: output.record.name, port, boost: root.service.boostFor(output.record.deviceKey)});
            }
        }
    }
    component OutputDevice: Surface {
        id: device
        required property var modelData
        readonly property var record: modelData
        objectName: "outputDevice:" + record.key
        Layout.fillWidth: true; implicitHeight: content.implicitHeight + 24
        color: Theme.surface; border.width: 0; radius: Theme.controlRadius
        ScriptModel {
            id: sinksModel
            values: root.outputs.filter(output => output.deviceKey === device.record.key && output.available)
            objectProp: "key"
        }
        ColumnLayout {
            id: content
            anchors.fill: parent; anchors.margins: 12; spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Heading { text: device.record.label; wrapMode: Text.Wrap }
                IconButton {
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
                            delegate: ShellMenuItem {
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
                        property ShellMenuItem boostItem: ShellMenuItem {
                            objectName: "audioBoost:" + device.record.key; text: qsTr("Boost audio")
                            marked: root.service.boostFor(device.record.key)
                            Accessible.checkable: true; Accessible.checked: marked
                            enabled: root.canAct
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
            IconButton { iconName: "refresh-cw"; text: qsTr("Refresh audio devices"); onClicked: root.service.refresh() }
            IconButton { iconName: "x"; text: qsTr("Dismiss audio error"); onClicked: root.service.error = "" }
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
            Note { objectName: "audioOutputsEmpty"; visible: root.service.loaded && !devicesModel.values.length; text: qsTr("No playback devices available.") }
            Repeater { model: devicesModel; delegate: OutputDevice {} }
            Heading { text: qsTr("Applications"); Layout.topMargin: 8 }
            Note { objectName: "audioAppsEmpty"; visible: root.service.loaded && !appsModel.values.length; text: qsTr("No applications are using audio.") }
            Repeater {
                model: appsModel
                delegate: ColumnLayout {
                    id: app
                    required property var modelData
                    readonly property var record: modelData
                    readonly property bool muted: record.node?.audio?.muted ?? false
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
                        Note { visible: app.muted; text: qsTr("Muted"); Layout.fillWidth: false }
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
                            volume: root.service.level(app.record.node); muted: app.muted; showPercentage: false
                            canVolume: !!app.record.node?.audio && !app.muted
                            canMute: !!app.record.node?.audio
                            maximum: root.boostForSink(app.record.target) ? 150 : 100
                            onVolumeEdited: value => root.service.setLevel(app.record.node, value)
                            onMuteClicked: root.service.setMuted(app.record.node, !app.muted)
                        }
                        IconButton {
                            id: appSettings
                            readonly property alias menu: routeMenu
                            objectName: "appOptions:" + app.record.key
                            iconName: "settings"; text: qsTr("Output for %1").arg(app.record.label)
                            hint: text + "\n" + (root.destinations.find(o => o.name === app.record.target)?.label ?? qsTr("Output unavailable"))
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
                                    delegate: ShellMenuItem {
                                        required property var modelData
                                        objectName: "appOutput:" + app.record.key + ":" + modelData.key
                                        text: modelData.label; marked: modelData.name === app.record.target
                                        Accessible.checkable: true; Accessible.checked: marked
                                        enabled: root.canAct && !root.service.busy
                                        onTriggered: root.service.move(app.record, modelData)
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
            canStart: root.canAct && !root.service.busy && root.destinations.some(node => !root.muted(node.name))
        }
    }
}
