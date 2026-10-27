pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import "../../ui"
import "Format.js" as Format

ColumnLayout {
    id: root
    property var session: PowerSession
    property bool active: false
    readonly property var recording: session.state.recording
    readonly property var summary: recording?.summary ?? null
    readonly property bool running: recording?.running ?? false
    Layout.fillWidth: true
    Layout.fillHeight: false
    spacing: 8
    RowLayout {
        visible: !!root.recording && !root.running
        Layout.fillWidth: true
        ShellText {
            text: qsTr("Last recording")
            Layout.fillWidth: true
            font.weight: Font.DemiBold
        }
        IconButton {
            objectName: "performanceRecordFolder"
            text: qsTr("Open recording folder")
            iconName: "folder-open"
            onClicked: Apps.launch(["xdg-open", root.recording.path])
        }
    }
    ShellText {
        visible: !!root.summary
        text: {
            const s = root.summary;
            if (!s)
                return "";
            const lines = [s.measured_seconds > 0 ? qsTr("Recorded %1").arg(Format.duration(s.measured_seconds)) : qsTr("Recorded %1 samples").arg(s.samples ?? 0)];
            if (s.cpu_usage !== undefined && s.cpu_usage !== null)
                lines.push(qsTr("Average CPU: %1").arg(Format.compact(s.cpu_usage, "%")));
            const temperatures = Object.values(s.observed_peak_temperatures_c ?? {}).filter(x => x !== null);
            if (temperatures.length)
                lines.push(qsTr("Peak temperature: %1").arg(Format.compact(Math.max(...temperatures), " °C")));
            if (s.peak_memory_used !== undefined && s.peak_memory_used !== null)
                lines.push(qsTr("Peak memory: %1").arg(Format.bytes(s.peak_memory_used)));
            for (const [name, b] of Object.entries(s.batteries ?? {}))
                if (b.mean_w !== undefined)
                    lines.push(qsTr("%1 average drain: %2").arg(name).arg(Format.compact(b.mean_w, " W", 1)));
            return lines.join("\n");
        }
        font.pixelSize: Theme.smallFontSize
        Layout.fillWidth: true
        wrapMode: Text.Wrap
    }
    ShellText {
        visible: !!root.recording && !root.running && (text !== "")
        text: root.recording?.error || root.summary?.abort_reason || (root.summary?.interrupted ? qsTr("Recording stopped early.") : "")
        color: Theme.warning
        font.pixelSize: Theme.smallFontSize
        Layout.fillWidth: true
        wrapMode: Text.Wrap
    }
    RowLayout {
        objectName: "performanceRecordRow"
        Layout.fillWidth: true
        spacing: 8
        DrawerActionButton {
            id: recordButton
            objectName: "performanceRecord"
            Layout.fillWidth: true
            Layout.fillHeight: true
            horizontalPadding: 6
            text: root.running ? qsTr("Stop recording") : qsTr("Record performance")
            iconName: root.running ? "square" : "circle-dot"
            enabled: root.active && root.session.ready && !root.session.busy
            onClicked: root.session.send(root.running ? {
                op: "stop-recording"
            } : {
                op: "record"
            })
            PassiveToolTip {
                target: recordButton
                text: root.running ? qsTr("Stop recording the current workload.") : qsTr("Record the current workload until stopped.")
            }
        }
    }
}
