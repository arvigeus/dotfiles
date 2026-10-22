pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Only opening connection information may start a lookup. Cache successes for ten
// minutes and failures for one; a route change invalidates either immediately.
Singleton {
    id: root
    property string context: ""
    property string address: ""
    property real checkedAt: 0
    property bool failed: false
    property string requestContext: ""
    property string output: ""
    property bool queued: false
    property bool busy: false
    readonly property string label: busy ? qsTr("Checking…") : address || (failed ? qsTr("Unavailable") : qsTr("Not checked"))
    onContextChanged: {
        address = ""; checkedAt = 0; failed = false; queued = false;
    }
    function lookup(): void {
        if (!context) return;
        if (busy) { queued = requestContext !== context; return; }
        const age = Date.now() - checkedAt;
        if (checkedAt && age >= 0 && age < (failed ? 60000 : 600000)) return;
        requestContext = context; output = ""; queued = false;
        busy = true; lookupProcess.running = true;
    }
    Process {
        id: lookupProcess
        command: ["curl", "--ipv4", "--fail", "--silent", "--show-error", "--max-time", "2", "--max-filesize", "64", "https://api.ipify.org"]
        stdout: StdioCollector { onStreamFinished: root.output = text.trim() }
        stderr: StdioCollector {}
        onExited: (code, status) => {
            if (root.requestContext === root.context) {
                const parts = root.output.split(".");
                const valid = code === 0 && parts.length === 4 && parts.every(part => /^\d{1,3}$/.test(part) && Number(part) <= 255);
                root.address = valid ? root.output : "";
                root.failed = !valid; root.checkedAt = Date.now();
            }
            root.busy = false;
            if (root.queued) Qt.callLater(root.lookup);
        }
    }
    Timer {
        id: watchdog
        interval: 3000; running: root.busy
        onTriggered: lookupProcess.running = false
    }
}
