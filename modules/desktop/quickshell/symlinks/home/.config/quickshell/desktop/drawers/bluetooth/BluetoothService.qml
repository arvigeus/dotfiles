pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Bluetooth
import Quickshell.Io

// Device actions use Quickshell.Bluetooth; pairing runs in backend.py because
// BlueZ sends PIN/passkey prompts only to the agent of the Pair() caller.
Singleton {
    id: root
    property QtObject pairingDevice: null
    // Pair() succeeded and the helper is trusting/connecting; dismissal no longer cancels.
    property bool pairingConnects: false
    property var prompt: null
    property string error: ""
    // dbusPath of the device the error belongs to; "" for drawer-wide errors.
    property string errorKey: ""
    property bool finished: false
    // Discovery started from the drawer; it ends after 30 s, when pairing starts
    // or when the drawer stops it. Quickshell sends Start/StopDiscovery only when
    // its cached Discovering disagrees, and BlueZ refuses to stop a start still in
    // flight, so a stop requested before discovery is reported is applied once it
    // is. The drawer page is destroyed too soon after dismissal to wait for that.
    property QtObject scanAdapter: null
    property bool scanning: false

    function fail(device, message: string): void {
        error = message;
        errorKey = device?.dbusPath ?? "";
    }
    function watch(device, op: string): void {
        error = "";
        settleWatch.createObject(root, {
            target: device,
            op
        });
    }
    function connect(device): void {
        watch(device, "connect");
        // Connecting authorizes the device's future reconnections; observation never does.
        if (!device.trusted)
            device.trusted = true;
        device.connect();
    }
    function disconnect(device): void {
        watch(device, "disconnect");
        device.disconnect();
    }
    function forget(device): void {
        error = "";
        device.forget();
    }
    function startScan(adapter): void {
        stopScan();
        scanAdapter = adapter;
        scanning = true;
        adapter.discovering = true;
    }
    function stopScan(): void {
        scanning = false;
        if (scanAdapter?.discovering) {
            scanAdapter.discovering = false;
            scanAdapter = null;
        }
    }
    function pair(device): void {
        if (pairingDevice || pairer.running)
            return;
        // Discovery competes with pairing for the radio.
        stopScan();
        error = "";
        prompt = null;
        pairingConnects = false;
        finished = false;
        pairingDevice = device;
        pairer.command = ["python3", Quickshell.shellPath("drawers/bluetooth/backend.py"), device.dbusPath, device.address];
        pairer.running = true;
    }
    function send(request): void {
        pairer.write(JSON.stringify(request) + "\n");
    }
    function respond(accept: bool, value: string): void {
        if (prompt && pairer.running) {
            error = "";
            send({
                op: "respond",
                id: prompt.id,
                accept,
                value
            });
        }
    }
    function cancel(): void {
        if (pairer.running && !pairingConnects)
            send({
                op: "cancel"
            });
    }
    function receive(line: string): void {
        let result;
        try {
            result = JSON.parse(line);
        } catch (_) {
            return;
        }
        if (result.type === "prompt")
            prompt = result.prompt;
        else if (result.type === "connecting")
            pairingConnects = true;
        else if (result.type === "error")
            fail(pairingDevice, result.error);
        else if (result.type === "done") {
            finished = true;
            if (result.error)
                fail(pairingDevice, result.error);
        }
    }

    Timer {
        interval: 30000
        running: root.scanning
        onTriggered: root.stopScan()
    }
    Connections {
        target: root.scanning ? null : root.scanAdapter
        function onDiscoveringChanged(): void {
            root.stopScan();
        }
    }

    // Native calls report failure only by returning to the previous state, so
    // each connect/disconnect is watched until its device settles.
    Component {
        id: settleWatch
        Connections {
            id: settling
            property string op
            function onStateChanged(): void {
                const device = settling.target;
                if (device.state === BluetoothDeviceState.Connecting || device.state === BluetoothDeviceState.Disconnecting)
                    return;
                if (op === "connect" && !device.connected)
                    root.fail(device, qsTr("Could not connect. Make sure the device is awake and nearby."));
                else if (op === "disconnect" && device.connected)
                    root.fail(device, qsTr("Could not disconnect this device."));
                settling.target = null;
                settling.destroy();
            }
        }
    }
    Process {
        id: pairer
        stdinEnabled: true
        stdout: SplitParser {
            onRead: line => root.receive(line)
        }
        stderr: SplitParser {
            onRead: line => console.warn("Bluetooth pairing helper:", line)
        }
        // A helper that fails to start emits no exited signal.
        onRunningChanged: if (!running) {
            if (!root.finished)
                root.fail(root.pairingDevice, qsTr("Bluetooth pairing helper stopped."));
            root.pairingDevice = null;
            root.pairingConnects = false;
            root.prompt = null;
        }
    }
}
