pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root
    readonly property alias updates: updates
    property var values: []
    property bool loaded: false
    property var owners: []
    property var queue: []
    property var request: null
    property bool closing: false
    property bool refreshPending: false
    property string actionError: ""
    property string statusError: ""
    readonly property string error: actionError || statusError
    readonly property bool busy: request !== null || queue.length > 0

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
    function enqueue(record, op: string, fields): void {
        actionError = "";
        const change = Object.assign({
            op,
            key: record.key,
            identity: record.identity,
            maximum: record.maximum,
            lightingPath: record.lightingPath || ""
        }, fields);
        change.coalesce = record.key + ":" + op + (op === "lighting" ? (fields.color ? ":color" : ":effect") : "");
        queue = queue.filter(item => item.coalesce !== change.coalesce).concat([change]);
        pump();
    }
    function setBrightness(record, value: real): void {
        if (record.available)
            enqueue(record, "set", {
                value: Math.round(value)
            });
    }
    function setEffect(record, effect: int): void {
        enqueue(record, "lighting", {
            effect
        });
    }
    function setColor(record, color: string): void {
        enqueue(record, "lighting", {
            effect: record.effect,
            color
        });
    }
    function setMode(record, mode: int): void {
        enqueue(record, "mode", {
            mode
        });
    }
    function pump(): void {
        if (request || closing)
            return;
        if (queue.length) {
            request = queue[0];
            queue = queue.slice(1);
        } else if (refreshPending && owners.length) {
            refreshPending = false;
            request = {
                op: "status"
            };
        } else {
            if (!owners.length) {
                refreshPending = false;
                if (worker.running) {
                    closing = true;
                    worker.running = false;
                }
            }
            return;
        }
        if (worker.running)
            worker.write(JSON.stringify(request) + "\n");
        else
            worker.running = true;
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
                error: qsTr("Could not read keyboard lighting.")
            };
        }
        const failure = result.error || (!result.ok ? qsTr("Could not read or change keyboard lighting.") : "");
        if (!failure) {
            values = result.values;
            loaded = true;
        }
        if (request.op !== "status") {
            actionError = failure;
            if (failure)
                refreshPending = true;
        } else
            statusError = failure;
        request = null;
        Qt.callLater(root.pump);
    }
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/keyboard/backlight.py")]
        stdinEnabled: true
        onStarted: if (root.request)
            write(JSON.stringify(root.request) + "\n")
        stdout: SplitParser {
            onRead: line => root.receive(line)
        }
        stderr: StdioCollector {}
        onExited: {
            if (root.request) {
                root.actionError = qsTr("Keyboard lighting helper stopped. Reopen the drawer to retry.");
                root.request = null;
                root.queue = [];
            }
            root.closing = false;
            if (root.queue.length || root.refreshPending)
                Qt.callLater(root.pump);
        }
    }
    Timer {
        id: updates
        interval: 1000
        repeat: true
        running: root.owners.length > 0
        onTriggered: root.refresh()
    }
}
