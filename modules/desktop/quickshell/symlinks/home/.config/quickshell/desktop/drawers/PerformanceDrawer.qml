pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../ui"
import "network"
import "network/Models.js" as Models
import "power"
import "power/Format.js" as Format

DrawerPage {
    id: root
    property var service: PowerService
    property var session: PowerSession
    readonly property var profiles: service.state.profiles
    readonly property var metrics: service.state.metrics
    readonly property bool canAct: active && service.loaded && !service.changing && !service.closing
    ListModel { id: profilesModel; dynamicRoles: true }
    ListModel { id: gpusModel; dynamicRoles: true }
    ListModel { id: fansModel; dynamicRoles: true }
    function sync(): void {
        Models.sync(profilesModel, profiles.choices.map(value => ({key: value})), "key", false);
        Models.sync(gpusModel, metrics?.gpus ?? [], "key", false);
        Models.sync(fansModel, metrics?.fans ?? [], "key", false);
    }
    Connections { target: root.service; function onStateChanged(): void { root.sync(); } }
    Component.onCompleted: { sync(); service.observe(root, active, true); }
    Component.onDestruction: service.observe(root, false, true)
    onActiveChanged: service.observe(root, active, true)
    headerActions: RowLayout {
        spacing: 4
        NetworkIconButton {
            objectName: "performanceMonitor"; iconName: "list"; text: qsTr("Open system monitor")
            hint: qsTr("Open btop for processes and resource usage")
            onClicked: { Quickshell.execDetached(["xdg-terminal-exec", "btop"]); root.closeRequested(); }
        }
        NetworkIconButton {
            objectName: "performanceRefresh"; iconName: "refresh-cw"; text: qsTr("Refresh performance")
            enabled: !root.service.busy && !root.service.closing
            onClicked: root.service.refresh()
        }
    }
    component Note: ShellText {
        Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap; textFormat: Text.PlainText
    }
    ColumnLayout {
        anchors.fill: parent; spacing: 8
        DrawerColumn {
            objectName: "performanceScroll"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 0
            Note { visible: !root.service.loaded; text: qsTr("Reading system performance…") }
            Note { visible: root.service.statusError !== ""; text: root.service.statusError; color: Theme.danger }
            Note { objectName: "performanceActionError"; visible: root.service.actionError !== ""; text: root.service.actionError; color: Theme.danger }
            Note { visible: root.session.error !== ""; text: root.session.error; color: Theme.danger }
            ShellText { objectName: "performanceHeading"; text: qsTr("Mode"); Layout.fillWidth: true; font.weight: Font.DemiBold }
            ColumnLayout {
                objectName: "performanceModes"; Layout.fillWidth: true; spacing: 10
                RowLayout {
                    Layout.fillWidth: true; spacing: 6
                    Repeater {
                        model: profilesModel
                        delegate: Button {
                            id: profile
                            required property var record
                            readonly property string profileName: record.key
                            readonly property bool current: root.profiles.active === profileName
                            readonly property string description: ({"power-saver": qsTr("Conserve battery with efficient playback and quieter operation."), balanced: qsTr("Responsive everyday work with adaptive power use."), performance: qsTr("Sustained performance with active cooling.")})[profileName] || ""
                            objectName: "powerProfile:" + profileName
                            Layout.fillWidth: true; Layout.preferredWidth: 1
                            implicitHeight: root.width < 340 ? 38 : 60; padding: 6; hoverEnabled: true
                            enabled: root.canAct && !(profileName === "performance" && root.profiles.inhibited !== "")
                            Accessible.name: Format.profile(profileName); Accessible.role: Accessible.RadioButton; Accessible.checked: current
                            onClicked: if (!current) root.service.changeProfile(profileName)
                            background: ButtonBackground { idleColor: profile.current ? Theme.accentSurface : Theme.raised; highlighted: profile.hovered || profile.visualFocus || profile.current; pressed: profile.down }
                            contentItem: ColumnLayout {
                                spacing: 4
                                Icon { name: Format.profileIcon(profile.profileName); color: profile.current ? Theme.accent : Theme.text; Layout.alignment: Qt.AlignHCenter; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                                ShellText { visible: root.width >= 340; text: Format.profile(profile.profileName); font.pixelSize: Theme.smallFontSize; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight }
                            }
                            PassiveToolTip { target: profile; text: Format.profile(profile.profileName) + (profile.current ? qsTr(" · Selected") : "") + "\n" + profile.description }
                        }
                    }
                }
                Note { visible: !root.profiles.available; text: root.profiles.error }
                Note { visible: root.profiles.degraded !== ""; text: qsTr("Power policy warning: %1").arg(root.profiles.degraded); color: Theme.warning }
                Note { visible: root.profiles.inhibited !== ""; text: qsTr("Performance unavailable: %1").arg(root.profiles.inhibited); color: Theme.warning }
                Repeater { model: root.profiles.holds; delegate: Note { required property var modelData; text: qsTr("%1 requests %2: %3").arg(modelData.application || qsTr("An application")).arg(Format.profile(modelData.profile)).arg(modelData.reason) } }
            }
            ShellText { objectName: "performanceDevicesHeading"; text: qsTr("Devices"); Layout.fillWidth: true; Layout.topMargin: 8; font.weight: Font.DemiBold }
            PowerCard {
                visible: !!root.metrics; title: qsTr("CPU")
                Note { text: root.metrics?.cpu.label ?? ""; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                GridLayout {
                    Layout.fillWidth: true; columns: width < 310 ? 2 : 3; columnSpacing: 6; rowSpacing: 0
                    MetricChip { objectName: "cpuUsage"; iconName: "cpu"; label: qsTr("CPU utilization"); value: Format.compact(root.metrics?.cpu.usage, "%"); detail: qsTr("Load · 1 / 5 / 15 min: %1").arg(root.metrics?.cpu.load.join(" / ") ?? "—") }
                    MetricChip { iconName: "gauge"; label: qsTr("Average CPU frequency"); value: Format.compact(root.metrics?.cpu.frequency, " GHz", 2) }
                    MetricChip { iconName: "thermometer"; label: qsTr("CPU temperature"); value: Format.compact(root.metrics?.cpu.temperature, " °C") }
                }
            }
            PowerCard {
                visible: !!root.metrics; title: qsTr("Memory")
                RowLayout {
                    Layout.fillWidth: true
                    MetricChip { objectName: "memoryUsed"; iconName: "memory-stick"; label: qsTr("Memory in use"); value: Format.bytes(root.metrics?.memory.used); detail: qsTr("Total: %1\nMemory stalls · last 10 s: %2").arg(Format.bytes(root.metrics?.memory.total)).arg(Format.value(root.metrics?.memory.pressure, "%", 1)) }
                    MetricChip { iconName: "hard-drive"; label: qsTr("Swap used"); value: Format.bytes(root.metrics?.memory.swapUsed); detail: qsTr("Total swap: %1").arg(Format.bytes(root.metrics?.memory.swapTotal)) }
                }
            }
            Repeater {
                model: gpusModel
                delegate: PowerCard {
                    id: gpu
                    required property var record
                    readonly property string sampleHint: record.sampleAge > 1 ? qsTr("Last sampled %1 s ago").arg(Math.round(record.sampleAge)) : ""
                    title: record.label
                    Note { visible: gpu.record.sleeping; text: qsTr("Sleeping") }
                    GridLayout {
                        visible: !gpu.record.sleeping
                        Layout.fillWidth: true; columns: width < 310 ? 2 : 3; columnSpacing: 6; rowSpacing: 0
                        MetricChip { iconName: "monitor"; label: qsTr("GPU utilization"); value: Format.compact(gpu.record.usage, "%"); detail: qsTr("Driver: %1. Counters depend on driver support.").arg(gpu.record.driver || qsTr("Unavailable")) }
                        MetricChip { iconName: "memory-stick"; label: qsTr("Graphics memory used"); value: gpu.record.used === null ? "—" : Format.bytes(gpu.record.used); detail: qsTr("Total: %1").arg(Format.bytes(gpu.record.total)) }
                        MetricChip { iconName: "thermometer"; label: qsTr("GPU temperature"); value: Format.compact(gpu.record.temperature, " °C"); detail: gpu.sampleHint }
                        MetricChip { visible: gpu.record.junction !== undefined && gpu.record.junction !== null; iconName: "thermometer"; label: qsTr("GPU hotspot"); value: Format.compact(gpu.record.junction, " °C"); detail: gpu.sampleHint }
                        MetricChip { visible: gpu.record.memoryTemperature !== undefined && gpu.record.memoryTemperature !== null; iconName: "thermometer"; label: qsTr("GPU memory temperature"); value: Format.compact(gpu.record.memoryTemperature, " °C"); detail: gpu.sampleHint }
                    }
                }
            }
            PowerCard {
                visible: (root.metrics?.fans.length ?? 0) > 0; title: qsTr("Fans")
                GridLayout {
                    Layout.fillWidth: true; columns: 2; rowSpacing: 0; columnSpacing: 6
                    Repeater { model: fansModel; delegate: MetricChip { required property var record; iconName: "fan"; label: record.label; value: Format.compact(record.rpm, " RPM") } }
                }
            }
        }
        PerformanceRecording { id: recordingControls; visible: root.session.ready && (root.session.state.recordAvailable || !!root.session.state.recording); session: root.session; active: root.active && !root.service.changing }
    }
}
