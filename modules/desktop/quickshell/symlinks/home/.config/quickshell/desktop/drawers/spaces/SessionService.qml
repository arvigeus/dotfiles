pragma Singleton
import QtQuick
import Quickshell.Io
import "../displays"

// The singleton lets a submitted command finish after the drawer is destroyed.
// No worker or polling remains while idle; systemd owns shutdown timers.
QtObject {
    id: root
    property var state: ({capabilities: {}, scheduledShutdown: ""})
    property string actionError: ""
    readonly property string error: actionError || ComfortService.error
    property bool actionBusy: false
    readonly property bool busy: actionBusy || ComfortService.busy
    readonly property bool pausesAvailable: !!ComfortService.state.pausesAvailable
    readonly property bool sleepPaused: !!ComfortService.state.sleepPaused
    readonly property bool lockingPaused: !!ComfortService.state.lockingPaused
    property bool received: false

    function refresh(): void { execute("status"); ComfortService.run("status"); }
    function setSleepPaused(value: bool): void { ComfortService.run("pause-sleep", {enabled: value}); }
    function setLockingPaused(value: bool): void { ComfortService.run("pause-locking", {enabled: value}); }
    function execute(action: string, minutes = 0): void {
        if (actionBusy || (action !== "status" && ComfortService.busy)) return;
        actionError = ""; actionBusy = true; received = false;
        worker.command = ["python3", "-B", decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, "")),
            JSON.stringify({action, minutes})];
        worker.running = true;
    }
    readonly property Process worker: Process {
        stdout: SplitParser {
            onRead: line => {
                root.received = true;
                try {
                    const result = JSON.parse(line);
                    if (result.ok) root.state = result.data;
                    else root.actionError = result.error || qsTr("Session action failed.");
                } catch (_) { root.actionError = qsTr("Could not read the session service response."); }
            }
        }
        stderr: StdioCollector {}
        onExited: (code, status) => {
            if (!root.received || code !== 0) root.actionError = qsTr("Session helper stopped. Reopen Spaces to retry.");
            root.actionBusy = false;
        }
    }
}
