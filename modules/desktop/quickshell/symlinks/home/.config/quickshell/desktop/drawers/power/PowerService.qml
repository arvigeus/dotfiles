pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Polls backend.py for telemetry, policy read-back and charge-limit providers
// while a drawer observes; battery and profile state are native UPower.
Singleton {
    id: root
    property var state: ({
            hardware: [],
            hardwareErrors: [],
            metrics: null,
            policy: ""
        })
    property bool loaded: false
    property string error: ""
    property var owners: []
    readonly property bool detailed: owners.some(entry => entry.details)
    readonly property int interval: detailed ? 2000 : 10000
    readonly property bool running: worker.running
    readonly property bool changing: PowerSession.busy
    property bool reading: false
    property bool again: false
    property bool closing: false

    function observe(owner, active: bool, details: bool): void {
        owners = owners.filter(entry => entry.owner !== owner).concat(active ? [
            {
                owner,
                details
            }
        ] : []);
        if (active)
            refresh();
        else if (!owners.length && !reading)
            stop();
    }
    function refresh(): void {
        if (!owners.length)
            return;
        if (reading) {
            again = true;
            return;
        }
        reading = true;
        // A stopping helper restarts once it exits; onStarted sends the request.
        if (worker.running && !closing)
            send();
        else
            worker.running = true;
    }
    function send(): void {
        worker.write(JSON.stringify({
            op: "status",
            details: detailed
        }) + "\n");
    }
    function stop(): void {
        if (worker.running) {
            closing = true;
            worker.running = false;
        }
    }
    function chargeLimit(row, value: int): void {
        PowerSession.send({
            op: "charge-limit",
            key: row.key,
            identity: row.identity,
            previous: row.limit,
            value
        });
    }
    function receive(line: string): void {
        reading = false;
        try {
            const result = JSON.parse(line);
            if (result.ok) {
                state = result.data;
                loaded = true;
                error = "";
            } else
                error = result.error || qsTr("Could not read power status.");
        } catch (_) {
            error = qsTr("Could not read power status.");
        }
        if (!owners.length)
            stop();
        else if (again) {
            again = false;
            refresh();
        }
    }

    Connections {
        target: PowerSession
        function onCompleted(): void {
            root.refresh();
        }
    }
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/power/backend.py")]
        stdinEnabled: true
        onStarted: {
            root.closing = false;
            if (root.reading)
                root.send();
        }
        stdout: SplitParser {
            onRead: line => root.receive(line)
        }
        onExited: {
            if (root.reading && !root.closing) {
                root.reading = false;
                root.error = qsTr("Power helper stopped. Refresh to retry.");
            }
            root.closing = false;
        }
    }
    Timer {
        interval: root.interval
        repeat: true
        running: root.owners.length > 0
        onTriggered: root.refresh()
    }
}
