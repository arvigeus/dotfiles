import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: root
    property string device: ""
    property bool active: false
    property var state: ({
            token: "",
            controls: []
        })
    property string error: ""
    property var pending: null
    property var queue: []
    readonly property bool busy: worker.running || pending !== null
    property bool loaded: false
    function refresh(): void {
        if (!active || !device || busy)
            return;
        send({
            op: "status",
            device
        });
    }
    function setControl(key: string, value: int): void {
        if (!active)
            return;
        queue = queue.filter(request => request.key !== key).concat([
            {
                op: "set",
                device,
                token: state.token,
                key,
                value
            }
        ]);
        pump();
    }
    function pump(): void {
        if (!active || busy || !queue.length)
            return;
        const request = queue[0];
        queue = queue.slice(1);
        send(request);
    }
    function send(request): void {
        pending = request;
        worker.stdinEnabled = true;
        worker.running = true;
    }
    onActiveChanged: {
        if (active)
            refresh();
        else
            queue = [];
    }
    onDeviceChanged: {
        state = {
            token: "",
            controls: []
        };
        loaded = false;
        refresh();
    }
    Timer {
        id: poll
        interval: 5000
        repeat: true
        running: root.active
        onTriggered: root.refresh()
    }
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/capture/webcam.py")]
        onStarted: {
            write(JSON.stringify(root.pending) + "\n");
            stdinEnabled = false;
        }
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text);
                    if (result.ok) {
                        root.state = result;
                        root.error = "";
                    } else
                        root.error = result.error || qsTr("Camera settings unavailable.");
                } catch (_) {
                    root.error = qsTr("Could not read camera settings.");
                }
                root.loaded = true;
            }
        }
        stderr: StdioCollector {}
        onExited: {
            root.pending = null;
            Qt.callLater(root.pump);
        }
    }
}
