pragma Singleton
import QtQuick
import Quickshell.Io

QtObject {
    id: root
    property var owners: []
    property var state: ({available: false, adapters: [], devices: []})
    property bool loaded: false
    property string error: ""
    property string errorKey: ""
    property string pending: ""
    property string pendingKey: ""
    property string scanning: ""
    property var prompt: null
    property bool starting: false
    property bool closing: false
    readonly property bool busy: pending !== ""
    function observe(owner, active: bool): void {
        owners = owners.filter(item => item !== owner).concat(active ? [owner] : []);
        if (closing) return;
        if (owners.length && !worker.running) start();
        else if (worker.running && !starting) send({op: "observe", active: owners.length > 0});
    }
    function start(): void { loaded = false; starting = true; worker.running = true; }
    function send(request): void { worker.write(JSON.stringify(request) + "\n"); }
    function run(op: string, record, fields): void {
        // Pair/Connect authorize this device's future reconnections; observation never does.
        if (busy || !owners.length || starting || !worker.running) return;
        error = ""; errorKey = ""; pending = op; pendingKey = record.key;
        send(Object.assign({op, key: record.key, address: record.address}, fields || {}));
    }
    function stopScan(): void { if (worker.running) send({op: "stop-scan"}); }
    function cancel(): void { if (worker.running) send({op: "cancel"}); }
    function respond(accept: bool, value: string): void {
        if (prompt) { error = ""; errorKey = ""; send({op: "respond", id: prompt.id, accept, value}); }
    }
    function receive(line: string): void {
        let result;
        try { result = JSON.parse(line); }
        catch (_) { error = qsTr("Could not read Bluetooth status."); return; }
        if (result.type === "state") { state = result; loaded = true; }
        else if (result.type === "pending") { pending = result.op; pendingKey = result.key; }
        else if (result.type === "scan") scanning = result.key;
        else if (result.type === "prompt") prompt = result.prompt;
        else if (result.type === "done") {
            if (result.error) { error = result.error; errorKey = result.key || pendingKey; }
            pending = ""; pendingKey = "";
        } else if (result.type === "error") {
            error = result.error; errorKey = pendingKey;
            // Validation failures have no pending event; input errors retain pairing.
            if (!result.busy) { pending = ""; pendingKey = ""; }
        }
        if (!owners.length && !busy && !closing) { closing = true; worker.running = false; }
    }
    readonly property Process worker: Process {
        command: ["python3", "-u", decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, ""))]
        stdinEnabled: true
        onStarted: { root.starting = false; root.send({op: "observe", active: root.owners.length > 0}); }
        stdout: SplitParser { onRead: line => root.receive(line) }
        stderr: StdioCollector {}
        onExited: {
            const expected = root.closing;
            root.closing = false;
            root.starting = false; root.scanning = ""; root.prompt = null;
            if (!expected && (root.owners.length || root.busy)) {
                root.errorKey = "";
                root.error = qsTr("Bluetooth helper stopped. Reopen the drawer to retry.");
            }
            root.pending = ""; root.pendingKey = "";
            if (expected && root.owners.length) Qt.callLater(root.start);
        }
    }
}
