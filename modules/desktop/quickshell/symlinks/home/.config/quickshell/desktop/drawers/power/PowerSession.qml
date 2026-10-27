pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower

// session.py owns charge-once and recording lifetimes; started once from shell.qml.
Singleton {
    id: root
    property bool started: false
    property bool ready: false
    property int pending: 0
    readonly property bool busy: pending > 0 || (started && !ready)
    property var state: ({
            once: null,
            recording: null,
            recordAvailable: false,
            error: ""
        })
    property string transportError: ""
    readonly property string error: transportError || state.error
    // UPower's OnBattery, or null without a ready laptop battery; restores charge-once on unplug.
    readonly property var batteryPower: UPower.displayDevice?.ready && UPower.displayDevice.isLaptopBattery ? UPower.onBattery : null
    signal completed
    function start(): void {
        started = true;
        worker.running = true;
    }
    function send(request): void {
        if (!ready || !worker.running)
            return;
        pending++;
        worker.write(JSON.stringify(request) + "\n");
    }
    function report(): void {
        if (ready)
            worker.write(JSON.stringify({
                op: "power",
                onBattery: batteryPower
            }) + "\n");
    }
    onBatteryPowerChanged: report()
    onReadyChanged: report()
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/power/session.py"), "--supervise"]
        stdinEnabled: true
        stdout: SplitParser {
            onRead: line => {
                try {
                    const response = JSON.parse(line);
                    root.state = response.state;
                    root.ready = true;
                    root.transportError = "";
                    if (response.reply) {
                        root.pending = Math.max(0, root.pending - 1);
                        root.completed();
                    }
                } catch (_) {
                    root.transportError = qsTr("Could not read power utility status.");
                }
            }
        }
        onExited: {
            root.ready = false;
            root.pending = 0;
            root.transportError = qsTr("Power utilities stopped; reconnecting…");
            if (root.started)
                retry.restart();
        }
    }
    Timer {
        id: retry
        interval: 5000
        onTriggered: if (root.started)
            worker.running = true
    }
}
