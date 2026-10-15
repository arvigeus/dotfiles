pragma Singleton
import QtQuick
import QtCore
import Quickshell
import Quickshell.Io

// Imported only by the Wi-Fi page. Operations survive page dismissal; observation
// and scanning stop immediately. No process runs before the first observation.
QtObject {
    id: root
    property bool observing: false
    property bool loaded: false
    property string interfaceName: ""
    property string error: ""
    property var failure: null
    property var actionContext: null
    property var previousTraffic: null
    property var traffic: ({})
    property string pending: ""
    property string pendingKey: ""
    property var request: null
    property bool received: false
    property bool refreshQueued: false
    property bool scanQueued: false
    property var queuedAction: null
    property string warpMode: "warp+doh"
    property bool warpRegisterNext: false
    readonly property Settings preferences: Settings {
        location: StandardPaths.writableLocation(StandardPaths.ConfigLocation) + "/quickshell/desktop/network.ini"
        category: "Network"
    }
    Component.onCompleted: {
        warpMode = preferences.value("warpMode", "warp+doh");
        warpRegisterNext = preferences.value("warpRegisterNext", false);
    }
    function selectWarpMode(mode: string): void {
        warpMode = mode;
        preferences.setValue("warpMode", mode);
        preferences.sync();
        if (state.warp?.running) run("warp", {action: "mode", mode}, "warp");
    }
    function setWarpRegistration(value: bool): void {
        warpRegisterNext = value;
        preferences.setValue("warpRegisterNext", value);
        preferences.sync();
    }
    readonly property bool working: pending !== ""
    // Background reads never dim or disable controls. A user action can queue
    // behind a read, then runs before the next refresh or scan.
    readonly property bool busy: queuedAction !== null || (working && !["status", "scan"].includes(pending))
    property var state: ({ available: false, wifiEnabled: false, hardwareEnabled: true,
        connectivity: "unknown", adapters: [], networks: [], profiles: [], wired: [],
        warp: { available: false, connected: false, running: false, state: "Checking…", mode: "" } })
    signal completed(string operation, bool success)

    function run(operation: string, values = {}, key = ""): void {
        if (process.running || request) {
            if (operation === "status") refreshQueued = true;
            else if (operation === "scan") scanQueued = true;
            else if (!busy) queuedAction = {operation, values, key};
            return;
        }
        if (operation !== "status" && operation !== "scan") dismissError();
        pending = operation;
        pendingKey = key;
        actionContext = {operation, key, uuid: values.uuid || "", interfaceName: values.interface || "",
            enabled: values.enabled, action: values.action, mode: values.mode, register: !!values.register};
        request = Object.assign({op: operation}, values);
        received = false;
        process.running = true;
    }
    function refresh(): void { run("status"); }
    function scan(): void {
        if (!observing || !state.wifiEnabled || !interfaceName) return;
        scanQueued = true;
        if (!working) { scanQueued = false; run("scan", {interface: interfaceName}); }
    }
    function applySnapshot(snapshot): void {
        sampleTraffic(snapshot);
        delete snapshot.sampleTime;
        if (failure) {
            const op = failure.operation;
            const profile = snapshot.profiles?.find(p => p.uuid === failure.uuid);
            const recovered = op === "status" || op === "scan"
                || (op === "connect" && ((profile?.state === "activated")
                    || snapshot.networks?.some(n => n.key === failure.key && n.connected)))
                || (op === "disconnect" && !profile?.active)
                || (op === "radio" && snapshot.wifiEnabled === failure.enabled)
                || (op === "warp" && (failure.action === "connect" ? snapshot.warp?.connected
                    : failure.action === "mode" ? snapshot.warp?.mode === failure.mode : !snapshot.warp?.running));
            if (recovered) dismissError();
        }
        // Reuse unchanged collections too: adapter choices and collapsed panels
        // should not react to a heartbeat that contains the same information.
        let changed = false;
        for (const key of Object.keys(snapshot)) {
            if (JSON.stringify(snapshot[key]) === JSON.stringify(state[key])) snapshot[key] = state[key];
            else changed = true;
        }
        if (changed) state = snapshot;
    }
    function dismissError(): void { error = ""; failure = null; }
    function sampleTraffic(snapshot): void {
        if (typeof snapshot.sampleTime !== "number") return;
        const values = {};
        for (const device of [...(snapshot.adapters || []), ...(snapshot.wired || [])]) {
            if (!device.connected || typeof device.traffic?.received !== "number") continue;
            const old = previousTraffic?.values[device.interface];
            const seconds = snapshot.sampleTime - (previousTraffic?.time ?? snapshot.sampleTime);
            values[device.interface] = {received: device.traffic.received, sent: device.traffic.sent};
            if (old && seconds > 0 && seconds < 30 && device.traffic.received >= old.received && device.traffic.sent >= old.sent)
                values[device.interface] = Object.assign(values[device.interface], {
                    down: (device.traffic.received - old.received) / seconds,
                    up: (device.traffic.sent - old.sent) / seconds});
        }
        previousTraffic = {time: snapshot.sampleTime, values};
        traffic = values;
    }
    onObservingChanged: {
        scanQueued = observing;
        if (observing) { previousTraffic = null; refresh(); }
        else scanDelay.stop();
    }
    onInterfaceNameChanged: if (observing) { scanQueued = true; scanDelay.restart(); }

    readonly property Process process: Process {
        command: ["python3", decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, ""))]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify(root.request) + "\n");
            root.request = null;
            stdinEnabled = false;
        }
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text);
                    root.received = true;
                    if (result.ok) {
                        root.applySnapshot(result.data);
                        if (root.pending === "warp" && root.actionContext?.action === "connect" && root.actionContext.register)
                            root.setWarpRegistration(false);
                        root.loaded = true;
                        if (!root.state.adapters.some(a => a.interface === root.interfaceName))
                            root.interfaceName = root.state.adapters[0]?.interface ?? "";
                    } else {
                        root.error = result.error || qsTr("The operation failed.");
                        root.failure = root.actionContext;
                        root.loaded = true;
                    }
                    root.completed(root.pending, !!result.ok);
                } catch (_) {
                    root.error = qsTr("Could not read network status. Refresh to retry.");
                    root.failure = root.actionContext;
                }
            }
        }
        // Never expose stderr: external tools may include credentials in errors.
        stderr: StdioCollector {}
        onExited: (code, status) => {
            const operation = root.pending;
            if (!root.received) {
                root.error = qsTr("Network helper stopped. Refresh to retry.");
                root.failure = root.actionContext;
                root.completed(operation, false);
            }
            root.pending = "";
            root.pendingKey = "";
            root.request = null;
            stdinEnabled = true;
            if (root.queuedAction) {
                const queued = root.queuedAction;
                root.queuedAction = null;
                root.run(queued.operation, queued.values, queued.key);
                return;
            }
            if (root.observing && (root.refreshQueued || !["status", "scan"].includes(operation))) {
                root.refreshQueued = false;
                Qt.callLater(root.refresh);
            }
            if (root.observing && operation === "radio") root.scanQueued = true;
            if (root.observing && root.scanQueued && root.state.wifiEnabled && root.interfaceName)
                scanDelay.restart();
        }
    }
    readonly property Timer poll: Timer {
        interval: 5000
        repeat: true
        running: root.observing
        onTriggered: if (!root.working) root.refresh()
    }
    readonly property Timer scanning: Timer {
        interval: 20000
        repeat: true
        running: root.observing && root.state.wifiEnabled
        onTriggered: root.scan()
    }
    readonly property Timer scanDelay: Timer {
        interval: 250
        onTriggered: root.scan()
    }
}
