pragma Singleton
import QtQuick
import Quickshell.Io

QtObject {
    id: root
    property var state: ({battery: {available: false, error: "", onBattery: null, batteries: [], summary: null},
        profiles: {available: false, active: "", choices: [], degraded: "", inhibited: "", holds: [], error: ""},
        hardware: [], hardwareErrors: [], metrics: null})
    property bool loaded: false
    property var owners: []
    readonly property bool detailed: owners.some(entry => entry.details)
    property var queue: []
    property var request: null
    property bool closing: false
    property bool refreshPending: false
    property string actionError: ""
    property string statusError: ""
    readonly property bool busy: request !== null || queue.length > 0
    readonly property bool changing: queue.length > 0 || (request !== null && request.op !== "status") || (PowerSession.started && PowerSession.busy)
    readonly property Connections utilities: Connections {
        target: PowerSession
        function onCompleted(): void { root.refresh(); }
    }

    function observe(owner, active: bool, details: bool): void {
        owners = owners.filter(entry => entry.owner !== owner).concat(active ? [{owner, details}] : []);
        if (active) refresh(); else pump();
    }
    function refresh(): void { refreshPending = true; pump(); }
    function changeProfile(value: string): void {
        enqueue({op: "profile", value, service: state.profiles.service,
            identity: state.profiles.identity, active: state.profiles.active});
    }
    function chargeLimit(row, value: int): void {
        enqueue({op: "charge-limit", key: row.key, identity: row.identity, previous: row.limit, value});
    }
    function enqueue(change): void {
        actionError = "";
        if (PowerSession.started) { PowerSession.send(change); return; }
        queue = queue.concat([change]);
        pump();
    }
    function pump(): void {
        if (request || closing) return;
        if (queue.length) { request = Object.assign({}, queue[0], {details: detailed}); queue = queue.slice(1); }
        else if (refreshPending && owners.length) { refreshPending = false; request = {op: "status", details: detailed}; }
        else {
            if (!owners.length) {
                refreshPending = false;
                if (worker.running) { closing = true; worker.running = false; }
            }
            return;
        }
        if (worker.running) worker.write(JSON.stringify(request) + "\n");
        else worker.running = true;
    }
    function receive(line: string): void {
        if (!request) return;
        let result;
        try { result = JSON.parse(line); }
        catch (_) { result = {ok: false, error: qsTr("Could not read the power service response.")}; }
        const failure = result.error || (!result.ok ? qsTr("Could not read or change power settings.") : "");
        if (!failure && result.data) { state = result.data; loaded = true; statusError = ""; }
        if (request.op === "status") statusError = failure;
        else { actionError = failure; if (failure) refreshPending = true; }
        request = null;
        Qt.callLater(root.pump);
    }
    readonly property Process worker: Process {
        command: ["python3", "-u", decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, ""))]
        stdinEnabled: true
        onStarted: if (root.request) write(JSON.stringify(root.request) + "\n")
        stdout: SplitParser { onRead: line => root.receive(line) }
        stderr: StdioCollector {}
        onExited: {
            if (root.request) {
                if (root.request.op === "status") root.statusError = qsTr("Power helper stopped. Refresh to retry.");
                else root.actionError = qsTr("Power helper stopped. Refresh to check the applied setting.");
                root.request = null; root.queue = [];
            }
            root.closing = false;
            if (root.queue.length || root.refreshPending) Qt.callLater(root.pump);
        }
    }
    readonly property Timer updates: Timer {
        interval: root.detailed ? 2000 : 10000
        repeat: true; running: root.owners.length > 0
        onTriggered: root.refresh()
    }
}
