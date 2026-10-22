pragma Singleton
import QtQuick
import QtCore
import Quickshell
import Quickshell.Io
import "../../ui"

// Helper state for what Quickshell.Networking lacks: VPN profiles, IP details,
// WARP and user-scoped profiles for new Wi-Fi networks. Reads run only while the
// drawer observes; operations survive dismissal. No process runs before then.
Singleton {
    id: root
    property bool observing: false
    property bool loaded: false
    property string interfaceName: ""
    property string error: ""
    property var failure: null
    property var actionContext: null
    property string pending: ""
    property string pendingKey: ""
    property var request: null
    property bool received: false
    property bool refreshQueued: false
    property var queuedAction: null
    property string warpMode: "warp+doh"
    property bool warpRegisterNext: false
    readonly property bool working: pending !== ""
    // Background reads never dim or disable controls. A user action can queue
    // behind a read, then runs before the next refresh.
    readonly property bool busy: queuedAction !== null || (working && pending !== "status")
    property var state: ({ profiles: [], active: [], details: ({}),
        warp: { available: false, connected: false, running: false, state: qsTr("Checking…"), mode: "" } })
    signal completed(string operation, bool success)

    // A separate application owns the picker, independent of the layer-shell
    // window that is hidden when the drawer closes.
    function chooseWireguardConfig(): void {
        Apps.launch(["python3", Quickshell.shellPath("drawers/network/backend.py"), "--import-wireguard"]);
    }

    Settings {
        id: preferences
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
    function run(operation: string, values = {}, key = ""): void {
        if (process.running || request) {
            if (operation === "status") refreshQueued = true;
            else if (!busy) queuedAction = {operation, values, key};
            return;
        }
        if (operation !== "status") dismissError();
        pending = operation;
        pendingKey = key;
        actionContext = {operation, key, uuid: values.uuid || "", action: values.action,
            mode: values.mode, register: !!values.register};
        request = Object.assign({op: operation}, values);
        received = false;
        process.running = true;
    }
    function refresh(): void { run("status"); }
    function dismissError(): void { error = ""; failure = null; }
    function applySnapshot(snapshot): void {
        if (failure) {
            const op = failure.operation;
            const profile = snapshot.profiles?.find(p => p.uuid === failure.uuid);
            const recovered = op === "status"
                || (op === "connect" && profile?.state === "activated")
                || (op === "disconnect" && !profile?.active)
                || (op === "warp" && (failure.action === "connect" ? snapshot.warp?.connected
                    : failure.action === "mode" ? snapshot.warp?.mode === failure.mode : !snapshot.warp?.running));
            if (recovered) dismissError();
        }
        // Reuse unchanged collections so models and popovers ignore identical reads.
        let changed = false;
        for (const key of Object.keys(snapshot)) {
            if (JSON.stringify(snapshot[key]) === JSON.stringify(state[key])) snapshot[key] = state[key];
            else changed = true;
        }
        if (changed) state = Object.assign({}, state, snapshot);
    }
    onObservingChanged: if (observing) refresh()

    Process {
        id: process
        command: ["python3", Quickshell.shellPath("drawers/network/backend.py")]
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
                    root.loaded = true;
                    if (result.ok) {
                        root.applySnapshot(result.data);
                        if (root.pending === "warp" && root.actionContext?.action === "connect" && root.actionContext.register)
                            root.setWarpRegistration(false);
                    } else {
                        root.error = result.error || qsTr("The operation failed.");
                        root.failure = root.actionContext;
                    }
                    root.completed(root.pending, !!result.ok);
                } catch (_) {
                    root.error = qsTr("Could not read network status. Reopen the drawer to retry.");
                    root.failure = root.actionContext;
                }
            }
        }
        // Never expose stderr: external tools may include credentials in errors.
        stderr: StdioCollector {}
        onExited: (code, status) => {
            const operation = root.pending;
            if (!root.received) {
                root.error = qsTr("Network helper stopped. Reopen the drawer to retry.");
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
            } else if (root.observing && root.refreshQueued) {
                root.refreshQueued = false;
                Qt.callLater(root.refresh);
            }
        }
    }
    // VPN and WARP state can change outside the drawer; WARP reports Connected
    // only after its connect command returns.
    Timer {
        interval: 10000
        repeat: true
        running: root.observing
        onTriggered: if (!root.working) root.refresh()
    }
}
