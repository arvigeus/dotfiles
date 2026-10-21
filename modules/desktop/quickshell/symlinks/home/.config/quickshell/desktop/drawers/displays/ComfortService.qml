pragma Singleton
import QtQuick
import Quickshell.Io

QtObject {
    id: root
    property bool loaded: false
    property bool ready: false
    property var request: null
    property var queue: []
    property var state: ({nightEnabled: false, nightAvailable: false, awake: {}, error: "", pausesAvailable: false, sleepPaused: false, lockingPaused: false})
    property string error: ""
    readonly property bool busy: request !== null || queue.length > 0
    function awakeFor(name: string): bool { return !!state.awake[name]; }
    function setAwake(record, enabled: bool): void { run("awake", {name: record.name, identity: record.identity, enabled}); }
    function start(): void { if (!worker.running) { ready = false; worker.running = true; } }
    function run(op: string, values = {}): void {
        error = "";
        queue = queue.concat([Object.assign({op}, values)]);
        start(); pump();
    }
    function pump(): void {
        if (!ready || request || !queue.length) return;
        request = queue[0]; queue = queue.slice(1);
        worker.write(JSON.stringify(request) + "\n");
    }
    readonly property Process worker: Process {
        command: ["python3", "-u", decodeURIComponent(Qt.resolvedUrl("comfort.py").toString().replace(/^file:\/\//, ""))]
        stdinEnabled: true
        stdout: SplitParser {
            onRead: line => {
                try {
                    const result = JSON.parse(line);
                    root.state = result.state; root.loaded = true; root.ready = true;
                    if (result.reply) root.request = null;
                    root.error = result.state.error;
                    Qt.callLater(root.pump);
                } catch (_) { root.error = qsTr("Could not read display comfort status."); }
            }
        }
        stderr: StdioCollector {}
        onExited: {
            root.ready = false; root.request = null; root.queue = [];
            root.state = Object.assign({}, root.state, {nightAvailable: false, nightEnabled: false, awake: {}, pausesAvailable: false, sleepPaused: false, lockingPaused: false});
            root.error = qsTr("Display comfort helper stopped. Reopen the drawer to retry.");
        }
    }
}
