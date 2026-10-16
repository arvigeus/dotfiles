pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

QtObject {
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
    readonly property bool busy: requestActive || selectionPending !== ""
    readonly property string selectingLanguage: selectionPending || (requestActive && worker.action === "select" ? worker.code : "")
    readonly property bool selecting: selectingLanguage !== ""
    readonly property string label: loaded ? language.toUpperCase() : "…"
    readonly property string description: error || (!loaded ? qsTr("Reading input language…")
        : languageName(language) + " · Alt+Shift: English / " + languageName(secondary))
    signal selectionFinished(string code, bool success)

    function languageName(code: string): string {
        return ({en: "English", bg: "Български", vi: "Tiếng Việt"})[code] || code;
    }
    function refresh(): void { request("status", keyboard); }
    function select(code: string): void {
        if (!["en", "bg", "vi"].includes(code) || (code === "vi" && !available)) return;
        keyboard = "";
        request("select", code);
    }
    function request(action: string, code: string): void {
        if (requestActive) {
            if (action === "select") selectionPending = code;
            else refreshPending = true;
            return;
        }
        worker.action = action;
        worker.code = code;
        worker.failure = "";
        worker.received = false;
        worker.result = null;
        if (action === "select") selectionError = "";
        worker.command = ["python3", Qt.resolvedUrl("backend.py").toString().replace("file://", ""), action, code];
        requestActive = true;
        worker.running = true;
    }
    function next(): void {
        if (requestActive) return;
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
        } else if (name === "configreloaded") layoutChanged.restart();
    }
    property Process worker: Process {
        property string action: "status"
        property string code: ""
        property string failure: ""
        property bool received: false
        property var result: null
        stdout: StdioCollector {
            onStreamFinished: {
                if (!text.trim()) return;
                try {
                    const state = JSON.parse(text);
                    if (!["en", "bg", "vi"].includes(state.language) || !["bg", "vi"].includes(state.secondary)
                        || typeof state.available !== "boolean") throw new Error("Invalid state");
                    root.worker.result = state;
                    root.worker.received = true;
                } catch (error) { root.worker.failure = qsTr("Could not read the input language."); }
            }
        }
        stderr: StdioCollector { onStreamFinished: if (text.trim()) root.worker.failure = text.trim(); }
        onExited: (exitCode, exitStatus) => {
            const failureText = failure || (exitCode || !received ? qsTr("Could not change or read the input language.") : "");
            if (!failureText) {
                root.language = result.language;
                root.secondary = result.secondary;
                root.available = result.available;
                root.loaded = true;
            }
            if (action === "select") {
                root.selectionError = failureText;
                if (failureText) root.refreshPending = true;
                root.selectionFinished(code, !failureText);
            } else root.statusError = failureText;
            root.requestActive = false;
            Qt.callLater(root.next);
        }
    }
    property Timer updates: Timer {
        // Provider mode changes have no XKB event. No daemon starts on reads.
        interval: 1000; repeat: true
        running: root.loaded && root.secondary === "vi"
        onTriggered: root.refresh()
    }
    property Timer layoutChanged: Timer { interval: 80; onTriggered: root.refresh() }
    property Connections events: Connections {
        target: Hyprland
        function onRawEvent(event): void { root.handleLayoutEvent(event.name, event.data); }
    }
    Component.onCompleted: if (Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE")) refresh();
}
