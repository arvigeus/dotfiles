pragma Singleton
import QtQuick
import Quickshell.Io

QtObject {
    id: root
    property var observers: []
    property bool started: false
    readonly property bool observing: observers.length > 0
    readonly property bool closing: worker.running && received
    property bool loaded: false
    property bool received: false
    property var request: null
    property var queue: []
    readonly property bool busy: (request !== null && request.op !== "status") || queue.some(item => item.op !== "status")
    property string error: ""
    property var brightness: ({})
    property bool brightnessLoaded: false
    property var brightnessQueue: []
    property var brightnessRequest: null
    property bool brightnessReceived: false
    function brightnessFor(name: string): var {
        const row = state.displays.find(row => row.name === name);
        const value = brightness[name];
        if (row && value && JSON.stringify(row.identity) === JSON.stringify(value.identity)) return value;
        return {available: false, value: 0, reason: brightnessLoaded ? qsTr("Brightness unavailable on this connection.") : qsTr("Checking brightness support…")};
    }
    function setBrightness(name: string, value: real): void {
        const record = brightness[name];
        if (!record?.available) return;
        error = "";
        const next = {op: "brightness", name, value, identity: record.identity, kind: record.kind, key: record.key};
        brightnessQueue = brightnessQueue.filter(item => item.op !== "status" && item.name !== name).concat([next]);
        brightnessPump();
    }
    function refreshBrightness(): void {
        if (!observing || brightnessQueue.some(item => item.op === "status") || brightnessRequest?.op === "status") return;
        brightnessQueue = brightnessQueue.concat([{op: "status"}]);
        brightnessPump();
    }
    function brightnessPump(): void {
        if (brightnessWorker.running || brightnessRequest || !brightnessQueue.length) return;
        brightnessRequest = brightnessQueue[0];
        brightnessQueue = brightnessQueue.slice(1);
        brightnessReceived = false;
        brightnessWorker.running = true;
    }
    readonly property Process brightnessWorker: Process {
        command: ["python3", "-u", decodeURIComponent(Qt.resolvedUrl("brightness.py").toString().replace(/^file:\/\//, ""))]
        stdinEnabled: true
        onStarted: { write(JSON.stringify(root.brightnessRequest) + "\n"); stdinEnabled = false; }
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text);
                    root.brightnessReceived = true; root.brightnessLoaded = true;
                    if (result.ok) {
                        const next = root.brightnessRequest?.op === "status" ? {} : Object.assign({}, root.brightness);
                        for (const record of result.values) next[record.name] = record;
                        root.brightness = next;
                    } else if (root.brightnessRequest?.op !== "status") root.error = result.error || qsTr("Could not change brightness.");
                } catch (_) { root.error = qsTr("Could not read brightness status."); }
            }
        }
        stderr: StdioCollector {}
        onExited: {
            if (!root.brightnessReceived && root.brightnessRequest?.op !== "status") root.error = qsTr("Brightness helper stopped.");
            root.brightnessRequest = null;
            stdinEnabled = true;
            Qt.callLater(root.brightnessPump);
        }
    }
    readonly property Timer brightnessPoll: Timer {
        interval: 5000; repeat: true; running: root.observing
        onTriggered: root.refreshBrightness()
    }
    property var state: ({available: false, displays: [], token: ""})
    // Session state stays in the shell; each helper invocation can exit after
    // one request without forgetting which changes came from restoration.
    property var baseline: null
    property bool restorePending: false
    function start(): void {
        if (started) return;
        started = true;
        run("restore");
    }
    function handleEvent(name: string, data: string): void {
        if (!started) return;
        if (name === "configreloaded") {
            restorePending = true;
            queue = queue.filter(item => !["sync", "status"].includes(item.op));
        }
        else if (!["monitoraddedv2", "monitorremoved"].includes(name)
            && !(name === "custom" && data === "desktop-displays-changed")) return;
        eventDelay.restart();
    }
    readonly property Timer eventDelay: Timer {
        interval: 500
        onTriggered: {
            const op = root.restorePending ? "restore" : "sync";
            root.restorePending = false;
            root.run(op);
        }
    }
    function observe(owner, active: bool): void {
        observers = observers.filter(item => item !== owner).concat(active ? [owner] : []);
    }
    function change(record, values): void {
        run("change", {name: record.name, identity: record.identity, values});
    }
    function run(op: string, values = {}): void {
        if (op === "status" && (request?.op === "status" || queue.some(item => item.op === "status"))) return;
        if (["sync", "restore"].includes(op) && queue.some(item => item.op === op)) return;
        if (op !== "status" && op !== "sync") error = "";
        queue = queue.concat([Object.assign({op}, values)]);
        pump();
    }
    function pump(): void {
        if (worker.running || request || !queue.length) return;
        request = queue[0]; queue = queue.slice(1);
        received = false;
        worker.running = true;
    }
    onObservingChanged: {
        if (observing) {
            refreshBrightness();
            run("status");
        } else {
            brightnessQueue = brightnessQueue.filter(item => item.op !== "status");
            queue = queue.filter(item => item.op !== "status");
        }
    }
    readonly property Process worker: Process {
        command: ["python3", "-u", decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, ""))]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify(Object.assign({}, root.request, {baseline: root.baseline})) + "\n");
            stdinEnabled = false;
        }
        stdout: SplitParser {
            onRead: line => {
                try {
                    const result = JSON.parse(line);
                    root.received = true; root.loaded = true;
                    if (JSON.stringify(root.state) !== JSON.stringify(result.data)) root.state = result.data;
                    if (result.baseline !== undefined) root.baseline = result.baseline;
                    else if (result.ok && root.request?.op !== "status") root.baseline = result.data;
                    if (!result.ok) root.error = result.error || qsTr("Could not change displays.");
                } catch (_) { root.error = qsTr("Could not read display status."); }
            }
        }
        stderr: StdioCollector {}
        onExited: {
            if (!root.received) {
                root.loaded = true;
                root.state = {available: false, displays: [], token: ""};
                root.error = qsTr("Display helper stopped. Refresh to retry.");
            }
            root.request = null;
            stdinEnabled = true;
            Qt.callLater(root.pump);
        }
    }
    function refresh(): void {
        error = "";
        refreshBrightness();
        run("sync");
    }
}
