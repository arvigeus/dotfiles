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
    property QtObject watched: null
    property string watchedOp: ""
    property bool finished: false

    function fail(device, message: string): void {
        error = message;
        errorKey = device?.dbusPath ?? "";
    }
    function watch(device, op: string): void {
        error = "";
        watched = device;
        watchedOp = op;
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
    function pair(device): void {
        if (pairingDevice || pairer.running)
            return;
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

    // Native calls report failure only by returning to the previous state.
    Connections {
        target: root.watched
        function onStateChanged(): void {
            const device = root.watched;
            if (device.state === BluetoothDeviceState.Connecting || device.state === BluetoothDeviceState.Disconnecting)
                return;
            if (root.watchedOp === "connect" && !device.connected)
                root.fail(device, qsTr("Could not connect. Make sure the device is awake and nearby."));
            else if (root.watchedOp === "disconnect" && device.connected)
                root.fail(device, qsTr("Could not disconnect this device."));
            root.watched = null;
        }
    }
    Process {
        id: pairer
        stdinEnabled: true
        stdout: SplitParser {
            onRead: line => root.receive(line)
        }
        onExited: {
            if (!root.finished)
                root.fail(root.pairingDevice, qsTr("Bluetooth pairing helper stopped."));
            root.pairingDevice = null;
            root.pairingConnects = false;
            root.prompt = null;
        }
    }
}
