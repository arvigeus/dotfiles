pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root
    property var entries: []
    property var results: []
    property bool busy: false
    property bool cleaning: false
    property string progress: ""
    property string error: ""
    property string input: ""
    property bool received: false
    // Delivery is replaceable in tests; results outlive the transient drawer.
    property var deliver: (title, body) => Quickshell.execDetached(["notify-send", "--app-name=System cleanup", "--icon=edit-clear", "--urgency=normal", "--", title, body.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")])
    function notifyResult(): void {
        if (!cleaning) {
            if (error)
                deliver(qsTr("Could not check cleanup options"), error);
            return;
        }
        const failed = results.filter(row => !row.ok);
        const done = results.length - failed.length;
        const title = error || failed.length ? qsTr("Cleanup needs attention") : qsTr("Cleanup complete");
        const summary = error || (failed.length ? (done ? qsTr("Cleaned %1 of %2 selected items.").arg(done).arg(results.length) : qsTr("The selected items could not be cleaned.")) : qsTr("Finished cleaning the selected items."));
        deliver(title, [summary].concat(failed.map(row => row.title + ": " + row.error)).join("\n\n"));
    }
    function scan(): void {
        if (!busy)
            start({
                op: "scan"
            });
    }
    function clean(selected): void {
        if (busy || !selected.length)
            return;
        results = [];
        start({
            op: "clean",
            selected: selected
        });
    }
    function start(request): void {
        busy = true;
        cleaning = request.op === "clean";
        error = "";
        progress = "";
        received = false;
        input = JSON.stringify(request) + "\n";
        worker.running = true;
    }
    function receive(line: string): void {
        try {
            const result = JSON.parse(line);
            if (result.progress) {
                progress = result.progress;
                return;
            }
            received = true;
            if (result.entries)
                entries = result.entries;
            if (result.results) {
                results = result.results;
            }
            error = result.error || "";
        } catch (_) {
            error = qsTr("Could not read the cleanup response.");
        }
    }
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/disks/cleanup.py")]
        stdinEnabled: true
        onStarted: {
            write(root.input);
            root.input = "";
        }
        stdout: SplitParser {
            onRead: line => root.receive(line)
        }
        stderr: StdioCollector {}
        onExited: {
            if (!root.received && !root.error)
                root.error = qsTr("The cleanup helper stopped. Try again.");
            root.notifyResult();
            root.busy = false;
            root.cleaning = false;
            root.progress = "";
        }
    }
}
