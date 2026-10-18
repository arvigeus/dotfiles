pragma Singleton
import QtQuick
import Quickshell.Io

QtObject {
    id: root
    property bool started: false
    property bool ready: false
    property int pending: 0
    readonly property bool busy: pending > 0 || (started && !ready)
    property var state: ({once: null, recording: null, recordAvailable: false, error: ""})
    property string transportError: ""
    readonly property string error: transportError || state.error
    signal completed()
    function start(): void { started = true; worker.running = true; }
    function send(request): void {
        if (!ready || !worker.running) return;
        pending++;
        worker.write(JSON.stringify(request) + "\n");
    }
    readonly property Process worker: Process {
        command: ["python3", "-B", "-u", decodeURIComponent(Qt.resolvedUrl("session.py").toString().replace(/^file:\/\//, "")), "--supervise"]
        stdinEnabled: true
        stdout: SplitParser {
            onRead: line => {
                try {
                    const response = JSON.parse(line);
                    root.state = response.state;
                    root.ready = true; root.transportError = "";
                    if (response.reply) { root.pending = Math.max(0, root.pending - 1); root.completed(); }
                } catch (_) { root.transportError = qsTr("Could not read power utility status."); }
            }
        }
        stderr: StdioCollector {}
        onExited: {
            root.ready = false; root.pending = 0;
            root.transportError = qsTr("Power utilities stopped; reconnecting…");
            if (root.started) retry.restart();
        }
    }
    readonly property Timer retry: Timer {
        interval: 5000
        onTriggered: if (root.started) root.worker.running = true
    }
}
