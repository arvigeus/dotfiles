pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root
    readonly property alias updates: updates
    readonly property alias worker: worker
    property var state: ({
            drives: [],
            editorAvailable: false,
            analyzerAvailable: false
        })
    property bool loaded: false
    property var owners: []
    property var request: null
    property string startupInput: ""
    property bool closing: false
    property bool refreshPending: false
    property string statusError: ""
    property string actionError: ""
    property string errorKey: ""
    property string message: ""
    property var healthResults: ({})
    readonly property bool busy: request !== null
    readonly property string pendingKey: request?.key ?? ""
    readonly property string pendingOp: request?.op ?? ""

    function observe(owner, active: bool): void {
        owners = owners.filter(item => item !== owner).concat(active ? [owner] : []);
        if (active)
            refresh();
        else
            pump();
    }
    function refresh(): void {
        refreshPending = true;
        pump();
    }
    function change(record, op: string, password = ""): void {
        if (busy || closing)
            return;
        actionError = "";
        errorKey = "";
        message = "";
        request = {
            op,
            key: record.key,
            identity: record.identity,
            label: record.label
        };
        // Retain only the serialized startup input until the pipe is ready.
        const payload = Object.assign({}, request);
        if (op === "unlock")
            payload.password = password;
        send(JSON.stringify(payload) + "\n");
    }
    function send(input: string): void {
        if (worker.running)
            worker.write(input);
        else {
            startupInput = input;
            worker.running = true;
        }
    }
    function healthFor(record): var {
        const result = healthResults[record.key];
        return result?.identity === record.identity ? result : null;
    }
    function dismissError(): void {
        actionError = "";
        errorKey = "";
    }
    function pump(): void {
        if (request || closing)
            return;
        if (refreshPending && owners.length) {
            refreshPending = false;
            request = {
                op: "status"
            };
            send(JSON.stringify(request) + "\n");
        } else if (!owners.length) {
            refreshPending = false;
            if (worker.running) {
                closing = true;
                worker.running = false;
            }
        }
    }
    function receive(line: string): void {
        if (!request)
            return;
        let result;
        try {
            result = JSON.parse(line);
        } catch (_) {
            result = {
                ok: false,
                error: qsTr("Could not read the storage response.")
            };
        }
        if (result.data) {
            state = result.data;
            loaded = true;
            statusError = "";
            const next = {};
            for (const drive of state.drives) {
                const existing = healthFor(drive);
                if (existing)
                    next[drive.key] = existing;
            }
            healthResults = next;
        }
        const failure = result.ok ? "" : result.error || qsTr("The storage operation failed.");
        if (request.op === "status")
            statusError = failure;
        else {
            actionError = failure;
            errorKey = failure ? request.key : "";
        }
        if (result.health)
            healthResults = Object.assign({}, healthResults, {
                [result.health.key]: result.health
            });
        message = result.message || "";
        request = null;
        Qt.callLater(root.pump);
    }
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/disks/backend.py")]
        stdinEnabled: true
        onStarted: {
            write(root.startupInput);
            root.startupInput = "";
        }
        stdout: SplitParser {
            onRead: line => root.receive(line)
        }
        stderr: StdioCollector {}
        onExited: {
            root.startupInput = "";
            if (root.request) {
                const failure = qsTr("The storage helper stopped. Refresh to retry.");
                if (root.request.op === "status")
                    root.statusError = failure;
                else {
                    root.actionError = failure;
                    root.errorKey = root.request.key;
                }
                root.request = null;
            }
            root.closing = false;
            if (root.refreshPending)
                Qt.callLater(root.pump);
        }
    }
    Timer {
        id: updates
        interval: 5000
        repeat: true
        running: root.owners.length > 0
        onTriggered: root.refresh()
    }
}
