import QtQuick
import Quickshell
import Quickshell.Io
import "../../ui"

Item {
    id: root
    property bool active: false
    property string section: ""
    property string readingSection: ""
    property bool loaded: false
    property bool timedOut: false
    property int generation: 0
    property int readingGeneration: 0
    property var state: ({
            os: "",
            kernel: "",
            uptime: null,
            kernelChanged: false,
            boot: {
                phases: [],
                total: "",
                summary: ""
            },
            slow: [],
            scopes: [],
            timers: [],
            errors: {},
            terminalAvailable: false
        })
    property string error: ""
    readonly property bool busy: readingSection !== ""
    readonly property string backend: Quickshell.shellPath("drawers/system/backend.py")
    property var launch: argv => Apps.launch(argv)
    function refresh(): void {
        if (!active || !section || readingSection)
            return;
        error = "";
        timedOut = false;
        readingSection = section;
        readingGeneration = generation;
        worker.running = true;
    }
    function openTerminal(action: string, scope = "system", unit = ""): void {
        if (action === "logs" && !state.terminalAvailable)
            return;
        if (!["update", "logs", "repair-signing", "check-packages"].includes(action))
            return;
        launch(["xdg-terminal-exec", "python3", backend, "--action", action, "--scope", scope, "--unit", unit]);
    }
    onActiveChanged: {
        generation++;
        if (!active)
            worker.running = false;
        else
            Qt.callLater(refresh);
    }
    onSectionChanged: {
        generation++;
        loaded = false;
        error = "";
        if (!section)
            worker.running = false;
        Qt.callLater(refresh);
    }
    Timer {
        interval: 30000
        repeat: true
        running: root.active && ["info", "services"].includes(root.section)
        onTriggered: root.refresh()
    }
    Timer {
        interval: 25000
        running: worker.running
        onTriggered: {
            root.timedOut = true;
            root.error = qsTr("System information timed out. Close and reopen this popup to retry.");
            worker.running = false;
        }
    }
    Process {
        id: worker
        command: ["python3", root.backend, "--section", root.readingSection]
        stdout: StdioCollector {
            id: output
        }
        stderr: StdioCollector {}
        onExited: (code, status) => {
            const requested = root.readingSection;
            root.readingSection = "";
            if (!root.active || !root.section)
                return;
            if (root.section !== requested || root.generation !== root.readingGeneration) {
                Qt.callLater(root.refresh);
                return;
            }
            if (root.timedOut)
                return;
            if (code !== 0) {
                root.error = qsTr("Could not read system information. Close and reopen this popup to retry.");
                return;
            }
            try {
                root.state = Object.assign({}, root.state, JSON.parse(output.text));
                root.loaded = true;
                root.error = "";
            } catch (_) {
                root.error = qsTr("Could not read system information. Close and reopen this popup to retry.");
            }
        }
    }
}
