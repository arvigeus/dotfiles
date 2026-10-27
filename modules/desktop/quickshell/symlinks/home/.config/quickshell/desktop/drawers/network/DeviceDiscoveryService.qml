pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root
    property var hosts: []
    property string subnet: ""
    property string error: ""
    property bool loaded: false
    property bool cancelled: false
    property string interfaceName: ""
    readonly property bool running: process.running
    function start(interfaceName: string): void {
        if (running || !interfaceName)
            return;
        root.interfaceName = interfaceName;
        error = "";
        hosts = [];
        subnet = "";
        loaded = false;
        cancelled = false;
        process.running = true;
    }
    function cancel(): void {
        cancelled = true;
        if (running)
            process.signal(15);
    }
    function clear(): void {
        cancel();
        hosts = [];
        subnet = "";
        loaded = false;
        error = "";
    }
    Process {
        id: process
        command: ["python3", Quickshell.shellPath("drawers/network/discovery.py"), root.interfaceName]
        stdout: StdioCollector {
            onStreamFinished: {
                if (root.cancelled)
                    return;
                try {
                    const reply = JSON.parse(text);
                    root.loaded = true;
                    if (reply.ok) {
                        root.hosts = reply.data.hosts;
                        root.subnet = reply.data.subnet;
                    } else
                        root.error = reply.error;
                } catch (_) {
                    root.error = qsTr("Could not read device discovery results.");
                }
            }
        }
        stderr: StdioCollector {}
        onExited: (code, status) => {
            if (!root.cancelled && code !== 0)
                root.error = qsTr("Device discovery stopped. Try again.");
        }
    }
}
