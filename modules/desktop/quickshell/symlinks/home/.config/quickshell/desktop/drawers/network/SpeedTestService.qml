pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Separate from NetworkService: measuring bandwidth never blocks network controls.
Singleton {
    id: root
    readonly property alias deadline: deadline
    readonly property bool running: process.running
    property var result: null
    property string error: ""
    property string response: ""
    property bool cancelled: false
    property bool timedOut: false
    // env execs the CLI; a missing package yields exit 127 instead of a stuck job.
    property list<string> command: ["env", "librespeed-cli", "--json", "--secure", "--no-icmp"]
    function start(): void {
        if (running) return;
        error = "";
        result = null;
        response = "";
        cancelled = false;
        timedOut = false;
        process.running = true;
    }
    function cancel(): void {
        if (!running) return;
        cancelled = true;
        process.signal(15);
        killDelay.restart();
    }
    function readResult(text: string): void {
        const report = JSON.parse(text)?.[0];
        if (!report || ![report.download, report.upload, report.ping, report.jitter]
            .every(value => typeof value === "number" && isFinite(value) && value >= 0))
            throw new Error("Invalid speed test result");
        // LibreSpeed's report stores Mbps and milliseconds. Retain no client IP/ISP data.
        result = {download: report.download, upload: report.upload, ping: report.ping,
            jitter: report.jitter, server: report.server?.name ?? "", timestamp: report.timestamp ?? ""};
    }
    Process {
        id: process
        command: root.command
        onStarted: deadline.restart()
        stdout: SplitParser { onRead: data => root.response += data }
        stderr: SplitParser {}
        onExited: (code, status) => {
            deadline.stop();
            killDelay.stop();
            if (!root.cancelled) {
                if (root.timedOut) root.error = qsTr("Speed test timed out. Try again.");
                else if (code === 127) root.error = qsTr("Install librespeed-cli-bin to run speed tests.");
                else if (code !== 0) root.error = qsTr("Speed test failed. Check the connection and try again.");
                else {
                    try { root.readResult(root.response); }
                    catch (_) { root.error = qsTr("The speed-test server returned no usable result. Try again."); }
                }
            }
            root.response = "";
        }
    }
    Timer {
        id: deadline
        interval: 120000
        onTriggered: { root.timedOut = true; process.signal(9); }
    }
    Timer {
        id: killDelay
        interval: 1000
        onTriggered: if (process.running) process.signal(9)
    }
}
