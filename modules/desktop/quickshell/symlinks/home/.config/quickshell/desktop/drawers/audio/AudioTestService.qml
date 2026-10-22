import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: root
    property string phase: "idle"
    property string detail: ""
    property string error: ""
    property string mode: ""
    property bool released: false
    property bool cancelled: false
    property bool started: false
    property bool completed: false
    readonly property bool running: phase !== "idle"
    property list<string> command: ["python3", Quickshell.shellPath("drawers/audio/probe.py")]
    function start(kind: string): void {
        if (running) return;
        mode = kind; phase = "starting"; detail = ""; error = "";
        released = false; cancelled = false; started = false; completed = false;
        worker.running = true;
    }
    function release(): void {
        released = true;
        if (started && worker.running) worker.write("release\n");
    }
    function cancel(): void {
        if (!running) return;
        cancelled = true;
        worker.signal(15);
        killDelay.restart();
    }
    Process {
        id: worker
        command: root.command
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify({op: root.mode}) + "\n");
            root.started = true;
            if (root.released) write("release\n");
            if (root.cancelled) signal(15);
            deadline.restart();
        }
        stdout: SplitParser {
            onRead: line => {
                if (root.cancelled) return;
                try {
                    const event = JSON.parse(line);
                    if (event.phase === "done" || event.phase === "error") root.completed = true;
                    if (event.phase === "error") root.error = event.error || qsTr("Audio test failed.");
                    else if (event.phase !== "done") { root.phase = event.phase; root.detail = event.detail || ""; }
                } catch (_) { root.error = qsTr("Could not read the audio test result."); root.cancel(); }
            }
        }
        stderr: StdioCollector {}
        onExited: code => {
            deadline.stop(); killDelay.stop();
            if (!root.cancelled && (code !== 0 || !root.completed) && !root.error) root.error = qsTr("Could not run the audio test.");
            root.phase = "idle"; root.detail = ""; root.started = false;
        }
    }
    Timer {
        id: deadline
        interval: 120000
        onTriggered: { root.error = qsTr("Audio test timed out."); root.cancel(); }
    }
    Timer {
        id: killDelay
        interval: 1500
        onTriggered: if (worker.running) worker.signal(9)
    }
    Component.onDestruction: cancel()
}
