pragma Singleton
import QtQuick
import QtCore
import Quickshell.Io

QtObject {
    id: root
    property bool observing: false
    property var observers: []
    property bool loaded: false
    property var boosts: ({})
    property string error: ""
    property bool readFailed: false
    property var state: ({available: false, outputs: [], outputDevices: [], streams: [], inputs: [], inputDevices: [], recordings: [], warning: ""})
    property var queue: []
    property var request: null
    property bool received: false
    property bool refreshQueued: false
    readonly property bool busy: request !== null && request.op !== "status"
    readonly property Settings preferences: Settings {
        location: StandardPaths.writableLocation(StandardPaths.ConfigLocation) + "/quickshell/desktop/audio.ini"
        category: "Playback"
    }
    Component.onCompleted: {
        try {
            const saved = JSON.parse(preferences.value("boostDevices", "{}"));
            const restored = {};
            if (saved && typeof saved === "object" && !Array.isArray(saved)) {
                for (const key of Object.keys(saved)) {
                    if (typeof saved[key] === "boolean" || saved[key] === "true" || saved[key] === "false")
                        restored[key] = saved[key] === true || saved[key] === "true";
                }
            }
            boosts = restored;
        } catch (_) { boosts = {}; }
        // Carry the earlier global preference forward until each device is set.
        const legacy = preferences.value("boost", false);
        if (boosts["*"] === undefined) boosts = Object.assign({"*": legacy === true || legacy === "true"}, boosts);
    }
    function boostFor(device: string): bool { return boosts[device] ?? boosts["*"] ?? false; }
    function boostPending(device: string): bool {
        return (request?.op === "output-boost" && request.device === device)
            || queue.some(action => action.op === "output-boost" && action.device === device);
    }
    function observe(owner, active: bool): void {
        observers = observers.filter(item => item !== owner).concat(active ? [owner] : []);
        observing = observers.length > 0;
    }
    function setBoost(device: string, value: bool): void {
        run("output-boost", {device, enabled: value});
    }
    function rememberBoost(device: string, value: bool): void {
        boosts = Object.assign({}, boosts, {[device]: value});
        preferences.setValue("boostDevices", JSON.stringify(boosts));
        preferences.sync();
    }
    function run(op: string, values = {}): void {
        if (op === "status") { refresh(); return; }
        error = "";
        readFailed = false;
        const next = Object.assign({op}, values);
        // Keep only the newest pending volume for each slider while preserving
        // ordered selections/mutes. The running action survives drawer dismissal.
        let pending = queue.slice();
        if (op === "volume" && pending.length) {
            const last = pending[pending.length - 1];
            if (last.op === op && last.kind === next.kind && last.name === next.name && last.token === next.token) pending.pop();
        }
        queue = pending.concat([next]);
        pump();
    }
    function refresh(): void { refreshQueued = true; pump(); }
    function fail(message: string): void {
        error = message;
        loaded = true;
        if (request?.op === "status") {
            readFailed = true;
            state = {available: false, outputs: [], outputDevices: [], streams: [], inputs: [], inputDevices: [], recordings: [], warning: ""};
        } else refreshQueued = true;
    }
    function pump(): void {
        if (process.running || request) return;
        if (queue.length) {
            request = queue[0];
            queue = queue.slice(1);
        } else if (refreshQueued && observing) {
            refreshQueued = false;
            request = {op: "status"};
        } else return;
        received = false;
        process.running = true;
    }
    onObservingChanged: {
        subscription.running = observing;
        if (observing) refresh();
        else { debounce.stop(); refreshQueued = false; }
    }
    readonly property Process process: Process {
        command: ["python3", decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, ""))]
        stdinEnabled: true
        onStarted: { write(JSON.stringify(root.request) + "\n"); stdinEnabled = false; }
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text);
                    root.received = true;
                    root.loaded = true;
                    if (result.ok) {
                        if (root.request?.op === "output-boost") root.rememberBoost(root.request.device, root.request.enabled);
                        if (JSON.stringify(result.data) !== JSON.stringify(root.state)) root.state = result.data;
                        if (root.readFailed) { root.error = ""; root.readFailed = false; }
                    } else {
                        root.fail(result.error || qsTr("Audio change failed."));
                    }
                } catch (_) { root.fail(qsTr("Could not read audio status. Refresh to retry.")); }
            }
        }
        stderr: StdioCollector {}
        onExited: {
            if (!root.received) root.fail(qsTr("Audio helper stopped. Refresh to retry."));
            root.request = null;
            stdinEnabled = true;
            Qt.callLater(root.pump);
        }
    }
    readonly property Process subscription: Process {
        command: ["pactl", "subscribe"]
        stdout: SplitParser {
            onRead: line => { if (/ on (sink|sink-input|source|source-output|card|server) #/.test(line)) debounce.restart(); }
        }
        stderr: StdioCollector {}
    }
    readonly property Timer debounce: Timer { interval: 120; onTriggered: if (root.observing) root.refresh() }
    // Also recovers if the server or subscription disappears while open.
    readonly property Timer recovery: Timer {
        interval: 5000; repeat: true; running: root.observing
        onTriggered: {
            root.refresh();
            if (!subscription.running) subscription.running = true;
        }
    }
}
