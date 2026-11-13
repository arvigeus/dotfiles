import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root
    required property var payload
    property bool active: false
    property int delay: 350
    property var result: null
    property string error: ""
    property int revision: 0
    property bool pending: false
    readonly property bool busy: active && (pending || helper.running)

    function reload(): void {
        revision++;
        result = null;
        error = "";
        debounce.stop();
        pending = active;
        if (helper.running)
            helper.signal(15);
        if (active)
            debounce.restart();
    }
    function launch(): void {
        if (!active || !pending || helper.running)
            return;
        pending = false;
        helper.epoch = revision;
        helper.value = payload;
        helper.answered = false;
        helper.open = true;
        helper.running = true;
    }
    onPayloadChanged: reload()
    onActiveChanged: reload()
    Timer {
        id: debounce
        interval: root.delay
        onTriggered: root.launch()
    }
    Process {
        id: helper
        property int epoch: -1
        property var value: ({})
        property bool answered: false
        property bool open: false
        function finish(): void {
            if (!open)
                return;
            open = false;
            stdinEnabled = true;
            if (root.active && epoch === root.revision && !answered)
                root.error = qsTr("Could not read the model registry. Try again.");
            if (!debounce.running)
                Qt.callLater(root.launch);
        }
        command: ["python3", Quickshell.shellPath("drawers/assistant/backend.py")]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify(value) + "\n");
            stdinEnabled = false;
        }
        stdout: SplitParser {
            onRead: line => {
                if (!root.active || helper.epoch !== root.revision)
                    return;
                helper.answered = true;
                try {
                    const value = JSON.parse(line);
                    if (value.type === "error")
                        root.error = value.error || qsTr("The model registry request failed.");
                    else if (value.type !== "cancelled")
                        root.result = value;
                } catch (_) {
                    root.error = qsTr("Could not read the model registry response.");
                }
            }
        }
        stderr: StdioCollector {}
        onExited: finish()
        onRunningChanged: if (!running && open)
            finish()
    }
}
