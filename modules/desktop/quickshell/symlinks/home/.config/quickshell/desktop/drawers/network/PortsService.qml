pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root
    readonly property alias process: process
    property bool observing: false
    property bool loaded: false
    property bool available: false
    property string error: ""
    property var ports: []
    property string operation: ""
    property var request: null
    property var queuedAction: null
    property bool received: false
    readonly property bool busy: queuedAction !== null || (operation !== "" && operation !== "status")
    signal completed(string operation, bool success)
    function run(op: string, values = {}): void {
        if (operation !== "" || process.running || request) {
            if (op !== "status" && !busy) queuedAction = {op, values};
            return;
        }
        operation = op; request = Object.assign({op}, values); received = false;
        if (op !== "status") error = "";
        process.running = true;
    }
    function refresh(): void { run("status"); }
    function finish(): void {
        if (operation === "") return;
        if (!received) {
            loaded = true; available = false;
            error = qsTr("Port helper unavailable. Install the firewall module.");
            completed(operation, false);
        }
        operation = ""; request = null; process.stdinEnabled = true;
        if (queuedAction) {
            const action = queuedAction; queuedAction = null;
            run(action.op, action.values);
        }
    }
    onObservingChanged: if (observing) refresh()
    Process {
        id: process
        command: ["/usr/local/libexec/firewall-ports"]
        stdinEnabled: true
        onRunningChanged: {
            if (!running && root.request) {
                const failedRequest = root.request;
                Qt.callLater(() => {
                    if (root.request === failedRequest && !running) root.finish();
                });
            }
        }
        onStarted: { write(JSON.stringify(root.request) + "\n"); root.request = null; stdinEnabled = false; }
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const response = JSON.parse(text);
                    root.received = true; root.loaded = true;
                    if (response.ok) {
                        if (JSON.stringify(root.ports) !== JSON.stringify(response.ports)) root.ports = response.ports;
                        root.available = true; root.error = "";
                    } else {
                        root.error = response.error || qsTr("Could not change port access.");
                        if (root.operation === "status") root.available = false;
                    }
                    root.completed(root.operation, !!response.ok);
                } catch (_) {}
            }
        }
        stderr: StdioCollector {}
        onExited: root.finish()
    }
    Timer {
        id: refreshTimer
        interval: 5000; repeat: true; running: root.observing
        onTriggered: root.refresh()
    }
}
