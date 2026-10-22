pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// The helper owns Keep awake and session-pause leases, so it lives as long as
// they do. It only reads systemd/Hyprland when asked: every few seconds while
// an observer is visible, and after output hotplug while Keep awake is set.
Singleton {
    id: root
    property var observers: []
    readonly property bool observing: observers.length > 0
    property bool loaded: false
    property bool ready: false
    property var request: null
    property var queue: []
    property var state: ({nightEnabled: false, nightAvailable: false, awake: {}, error: "", pausesAvailable: false, sleepPaused: false, lockingPaused: false})
    property string error: ""
    // Background reads must not disable the switches while they run.
    readonly property bool busy: (request !== null && !request.background) || queue.some(item => !item.background)
    // Test hook for the helper process.
    readonly property alias worker: worker
    function awakeFor(name: string): bool { return !!state.awake[name]; }
    function setAwake(record, enabled: bool): void { run("awake", {name: record.name, identity: record.identity, enabled}); }
    function observe(owner, active: bool): void {
        observers = observers.filter(item => item !== owner).concat(active ? [owner] : []);
    }
    onObservingChanged: if (observing) poll()
    // Drops Keep awake for outputs that disconnected or were replaced.
    function prune(): void { if (Object.keys(state.awake).length) poll(); }
    function poll(): void {
        if (request?.op !== "status" && !queue.some(item => item.op === "status")) run("status", {background: true});
    }
    function start(): void { if (!worker.running) { ready = false; worker.running = true; } }
    function run(op: string, values = {}): void {
        if (op !== "status") error = "";
        queue = queue.concat([Object.assign({op}, values)]);
        start(); pump();
    }
    function pump(): void {
        if (!ready || request || !queue.length) return;
        request = queue[0]; queue = queue.slice(1);
        worker.write(JSON.stringify(request) + "\n");
    }
    Timer {
        interval: 3000; repeat: true; running: root.observing && root.ready
        onTriggered: root.poll()
    }
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/displays/comfort.py")]
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
