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
    // The helper answers one line per request, in order. An action that arrives
    // during a status read waits in `queued` instead of being refused.
    property var request: null
    property var queued: null
    property string startupInput: ""
    property bool closing: false
    property bool refreshPending: false
    property string statusError: ""
    property string actionError: ""
    property string errorKey: ""
    property var healthResults: ({})
    readonly property var action: queued?.request ?? (request?.op === "status" ? null : request)
    readonly property bool busy: action !== null
    readonly property bool refreshing: request?.op === "status"
    readonly property string pendingKey: action?.key ?? ""
    readonly property string pendingOp: action?.op ?? ""

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
        const next = {
            op,
            key: record.key,
            identity: record.identity,
            label: record.label
        };
        // Retain only the serialized input until it is written to the pipe.
        const payload = Object.assign({}, next);
        if (op === "unlock")
            payload.password = password;
        const input = JSON.stringify(payload) + "\n";
        if (request)
            queued = {
                request: next,
                input
            };
        else {
            request = next;
            send(input);
        }
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
    function fail(lost, failure: string): void {
        if (lost.op === "status")
            statusError = failure;
        else {
            actionError = failure;
            errorKey = failure ? lost.key : "";
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
        fail(request, result.ok ? "" : result.error || qsTr("The storage operation failed."));
        if (result.health)
            healthResults = Object.assign({}, healthResults, {
                [result.health.key]: result.health
            });
        request = null;
        if (queued) {
            const next = queued;
            queued = null;
            request = next.request;
            send(next.input);
        } else
            Qt.callLater(root.pump);
    }
    // A failed start emits no `exited`; both paths end the same way. A lost
    // action is reported, never retried.
    function stopped(): void {
        startupInput = "";
        const failure = qsTr("The storage helper stopped. Refresh to retry.");
        for (const lost of [request, queued?.request])
            if (lost)
                fail(lost, failure);
        request = null;
        queued = null;
        closing = false;
        if (refreshPending)
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
        onExited: root.stopped()
        onRunningChanged: if (!running && root.request)
            root.stopped()
    }
    Timer {
        id: updates
        interval: 5000
        repeat: true
        running: root.owners.length > 0
        onTriggered: root.refresh()
    }
}
