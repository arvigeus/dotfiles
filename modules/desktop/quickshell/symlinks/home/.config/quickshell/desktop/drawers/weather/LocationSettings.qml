pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root
    property string selectedId: ""
    property string error: ""
    readonly property bool busy: worker.running
    signal changed
    function setCurrent(id: string): void {
        if (busy || !id)
            return;
        selectedId = id;
        error = "";
        worker.stdinEnabled = true;
        worker.running = true;
    }
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/weather/backend.py")]
        onStarted: {
            write(JSON.stringify({
                op: "current",
                id: root.selectedId
            }) + "\n");
            stdinEnabled = false;
        }
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text);
                    root.error = result.error || "";
                    if (!root.error) {
                        Date.timeZoneUpdated();
                        root.changed();
                    }
                } catch (_) {
                    root.error = qsTr("Could not save the current location.");
                }
            }
        }
        stderr: StdioCollector {}
    }
}
