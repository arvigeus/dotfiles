pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

Singleton {
    id: root
    property string language: "en"
    property string secondary: "bg"
    property bool available: false
    property bool loaded: false
    property string statusError: ""
    property string selectionError: ""
    readonly property string error: selectionError || statusError
    property string keyboard: ""
    property bool requestActive: false
    property bool refreshPending: false
    property string selectionPending: ""
    // The controller bounds each of its own steps; this only ends a hang.
    property int requestTimeout: 90000
    readonly property var controller: controllerCommand(controllerFile.text())
    readonly property bool busy: requestActive || selectionPending !== ""
    readonly property string selectingLanguage: selectionPending || (requestActive && worker.action === "select" ? worker.code : "")
    readonly property bool selecting: selectingLanguage !== ""
    readonly property string label: loaded ? language.toUpperCase() : "…"
    readonly property string description: error || (!loaded ? qsTr("Reading input language…") : languageName(language) + " · Alt+Shift: English / " + languageName(secondary))
    signal selectionFinished(string code, bool success)

    function languageName(code: string): string {
        return ({
                en: "English",
                bg: "Български",
                vi: "Tiếng Việt"
            })[code] || code;
    }
    function controllerCommand(text: string): var {
        try {
            const command = JSON.parse(text).command;
            if (Array.isArray(command) && command.length && command.every(argument => typeof argument === "string" && argument !== ""))
                return command;
        } catch (_) {}
        return null;
    }
    function validState(state): bool {
        return ["en", "bg", "vi"].includes(state?.language) && ["bg", "vi"].includes(state.secondary) && typeof state.available === "boolean";
    }
    function refresh(): void {
        request("status", keyboard);
    }
    function select(code: string): void {
        if (!["en", "bg", "vi"].includes(code) || (code === "vi" && !available))
            return;
        keyboard = "";
        request("select", code);
    }
    function request(action: string, code: string): void {
        if (requestActive) {
            if (action === "select")
                selectionPending = code;
            else
                refreshPending = true;
            return;
        }
        worker.action = action;
        worker.code = code;
        worker.failure = "";
        if (action === "select")
            selectionError = "";
        requestActive = true;
        if (!controller) {
            finish(qsTr("The input language controller is not installed."), null);
            return;
        }
        worker.command = controller.concat(code ? [action, code] : [action]);
        worker.running = true;
    }
    function finish(failure: string, state): void {
        if (!failure) {
            language = state.language;
            secondary = state.secondary;
            available = state.available;
            loaded = true;
        }
        requestActive = false;
        if (worker.action === "select") {
            selectionError = failure;
            if (failure)
                refreshPending = true;
            selectionFinished(worker.code, !failure);
        } else
            statusError = failure;
        Qt.callLater(root.next);
    }
    function next(): void {
        if (requestActive)
            return;
        if (selectionPending) {
            const code = selectionPending;
            selectionPending = "";
            request("select", code);
        } else if (refreshPending) {
            refreshPending = false;
            refresh();
        }
    }
    function handleLayoutEvent(name: string, data: string): void {
        if (name === "activelayout") {
            keyboard = data.slice(0, data.indexOf(","));
            layoutChanged.restart();
        } else if (name === "configreloaded")
            layoutChanged.restart();
    }
    // hardware/keyboard/input-method declares its controller here.
    FileView {
        id: controllerFile
        path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/input-language.json"
        blockLoading: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
    }
    Process {
        id: worker
        property string action: "status"
        property string code: ""
        property string failure: ""
        stdout: StdioCollector {
            id: output
        }
        stderr: StdioCollector {
            id: diagnostics
        }
        onExited: exitCode => {
            let state = null;
            try {
                state = JSON.parse(output.text);
            } catch (_) {}
            // The controller states the reason first; later lines are diagnostics.
            const reason = diagnostics.text.trim().split("\n")[0];
            if (failure)
                root.finish(failure, null);
            else if (exitCode)
                root.finish(reason || qsTr("Could not change or read the input language."), null);
            else
                root.finish(root.validState(state) ? "" : qsTr("Could not read the input language."), state);
        }
        // A controller that fails to start emits no exited signal.
        onRunningChanged: if (!running && root.requestActive)
            root.finish(qsTr("Could not start the input language controller."), null)
    }
    Timer {
        interval: root.requestTimeout
        running: root.requestActive
        onTriggered: {
            worker.failure = qsTr("The input language controller did not respond.");
            worker.running = false;
        }
    }
    Timer {
        id: updates
        // Provider mode changes have no XKB event. No daemon starts on reads.
        interval: 1000
        repeat: true
        running: root.loaded && root.secondary === "vi"
        onTriggered: root.refresh()
    }
    Timer {
        id: layoutChanged
        interval: 80
        onTriggered: root.refresh()
    }
    Connections {
        id: events
        target: Hyprland
        function onRawEvent(event): void {
            root.handleLayoutEvent(event.name, event.data);
        }
    }
    Component.onCompleted: if (Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE"))
        refresh()
}
