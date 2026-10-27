pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower

Singleton {
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
    property var state: ({
            available: false,
            displays: [],
            token: ""
        })
    property var powerProfiles: PowerProfiles
    readonly property string powerMode: powerProfiles.profile === PowerProfile.PowerSaver ? "power-saver" : "balanced"
    // Session-only policy state. An explicit panel refresh choice in Powersave
    // wins until the mode changes; a blank panel retries on the next event.
    property bool capSuppressed: false
    property bool powerPending: false
    readonly property bool capped: powerMode === "power-saver" && !capSuppressed
    property bool outputsChanged: false
    property bool reloaded: false
    // Test hooks for the helper processes and event debounce.
    readonly property alias worker: worker
    readonly property alias brightnessWorker: brightnessWorker
    readonly property alias eventDelay: eventDelay

    function brightnessFor(name: string): var {
        const row = state.displays.find(row => row.name === name);
        const value = brightness[name];
        if (row && value && JSON.stringify(row.identity) === JSON.stringify(value.identity))
            return value;
        return {
            available: false,
            value: 0,
            reason: brightnessLoaded ? qsTr("Brightness unavailable on this connection.") : qsTr("Checking brightness support…")
        };
    }
    function setBrightness(name: string, value: real): void {
        const record = brightness[name];
        if (!record?.available)
            return;
        error = "";
        const next = {
            op: "brightness",
            name,
            value,
            identity: record.identity,
            kind: record.kind,
            key: record.key
        };
        brightnessQueue = brightnessQueue.filter(item => item.op !== "status" && item.name !== name).concat([next]);
        brightnessPump();
    }
    function refreshBrightness(): void {
        if (!observing || brightnessQueue.some(item => item.op === "status") || brightnessRequest?.op === "status")
            return;
        brightnessQueue = brightnessQueue.concat([
            {
                op: "status"
            }
        ]);
        brightnessPump();
    }
    function brightnessPump(): void {
        if (brightnessWorker.running || brightnessRequest || !brightnessQueue.length)
            return;
        brightnessRequest = brightnessQueue[0];
        brightnessQueue = brightnessQueue.slice(1);
        brightnessReceived = false;
        brightnessWorker.running = true;
    }

    onPowerModeChanged: {
        capSuppressed = false;
        if (started)
            run("power");
    }
    function start(): void {
        if (started)
            return;
        started = true;
        run("ensure");
        if (capped)
            run("power");
    }
    function handleEvent(name: string, data: string): void {
        if (!started)
            return;
        if (["monitoraddedv2", "monitorremoved"].includes(name))
            outputsChanged = true;
        else if (name === "configreloaded")
            reloaded = true;
        else if (!(name === "custom" && data === "desktop-displays-changed"))
            return;
        eventDelay.restart();
    }
    function settle(): void {
        const outputs = outputsChanged, policy = powerPending || (reloaded && capped);
        outputsChanged = false;
        reloaded = false;
        if (outputs) {
            run("ensure");
            ComfortService.prune();
        }
        if (policy)
            run("power");
        if (!outputs && !policy && observing)
            run("status");
    }
    function observe(owner, active: bool): void {
        observers = observers.filter(item => item !== owner).concat(active ? [owner] : []);
    }
    function change(record, values): void {
        if (values.mode !== undefined && /^(eDP|LVDS|DSI)-/.test(record.name) && powerMode === "power-saver")
            capSuppressed = true;
        run("change", {
            name: record.name,
            identity: record.identity,
            values
        });
    }
    function save(): void {
        run("save");
    }
    function run(op: string, values = {}): void {
        if (op === "status" && (request?.op === "status" || queue.some(item => item.op === "status")))
            return;
        if (["ensure", "power"].includes(op) && queue.some(item => item.op === op))
            return;
        if (op !== "status")
            error = "";
        queue = queue.concat([Object.assign({
                op
            }, values)]);
        pump();
    }
    function pump(): void {
        if (worker.running || request || !queue.length)
            return;
        request = queue[0];
        queue = queue.slice(1);
        received = false;
        worker.running = true;
    }
    function refresh(): void {
        error = "";
        refreshBrightness();
        run("status");
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

    Timer {
        id: eventDelay
        interval: 500
        onTriggered: root.settle()
    }
    Timer {
        interval: 5000
        repeat: true
        running: root.observing
        onTriggered: root.refreshBrightness()
    }
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/displays/backend.py")]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify(Object.assign({}, root.request, {
                capped: root.capped
            })) + "\n");
            stdinEnabled = false;
        }
        stdout: SplitParser {
            onRead: line => {
                try {
                    const result = JSON.parse(line);
                    root.received = true;
                    root.loaded = true;
                    if (JSON.stringify(root.state) !== JSON.stringify(result.data))
                        root.state = result.data;
                    if (result.pending !== undefined)
                        root.powerPending = result.pending;
                    if (!result.ok)
                        root.error = result.error || qsTr("Could not change displays.");
                } catch (_) {
                    root.error = qsTr("Could not read display status.");
                }
            }
        }
        stderr: StdioCollector {}
        onExited: {
            if (!root.received) {
                root.loaded = true;
                root.state = {
                    available: false,
                    displays: [],
                    token: ""
                };
                root.error = qsTr("Display helper stopped. Refresh to retry.");
            }
            root.request = null;
            stdinEnabled = true;
            Qt.callLater(root.pump);
        }
    }
    Process {
        id: brightnessWorker
        command: ["python3", Quickshell.shellPath("drawers/displays/brightness.py")]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify(root.brightnessRequest) + "\n");
            stdinEnabled = false;
        }
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text);
                    root.brightnessReceived = true;
                    root.brightnessLoaded = true;
                    if (result.ok) {
                        const next = root.brightnessRequest?.op === "status" ? {} : Object.assign({}, root.brightness);
                        for (const record of result.values)
                            next[record.name] = record;
                        root.brightness = next;
                    } else if (root.brightnessRequest?.op !== "status")
                        root.error = result.error || qsTr("Could not change brightness.");
                } catch (_) {
                    root.error = qsTr("Could not read brightness status.");
                }
            }
        }
        stderr: StdioCollector {}
        onExited: {
            if (!root.brightnessReceived && root.brightnessRequest?.op !== "status")
                root.error = qsTr("Brightness helper stopped.");
            root.brightnessRequest = null;
            stdinEnabled = true;
            Qt.callLater(root.brightnessPump);
        }
    }
}
