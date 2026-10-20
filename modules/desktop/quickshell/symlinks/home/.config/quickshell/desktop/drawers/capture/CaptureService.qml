pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    id: root
    property var recorder: ({available: false, phase: "idle", elapsed: 0, options: {}, pictures: "", videos: "", lastVideo: ""})
    property string error: ""
    property string lastImage: ""
    property int delay: 0
    readonly property bool edit: editorPreference.text().trim() !== "off"
    readonly property bool save: savePreference.text().trim() !== "off"
    property string output: ""
    property double deadline: 0
    property double now: Date.now()
    property var pending: null
    property var launch: command => Quickshell.execDetached(command)
    readonly property bool waiting: pending !== null
    readonly property bool capturing: grabber.running
    readonly property int remaining: waiting ? Math.max(0, Math.ceil((deadline - now) / 1000)) : 0
    readonly property bool sessionActive: recorder.phase !== "idle"
    readonly property bool paused: recorder.phase === "paused"
    readonly property string recordingTime: Math.floor((recorder.elapsed || 0) / 60) + ":" + String((recorder.elapsed || 0) % 60).padStart(2, "0")
    readonly property bool savingRecordingOption: commander.running
    property bool recordingPending: false
    readonly property string backend: decodeURIComponent(Qt.resolvedUrl("recorder.py").toString().replace(/^file:\/\//, ""))
    signal hideRequested()
    readonly property FileView editorPreference: FileView {
        path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/desktop/screenshot-editor"
        blockLoading: true; watchChanges: true
        onFileChanged: reload()
        onSaved: reload()
    }
    readonly property FileView savePreference: FileView {
        path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/desktop/screenshot-save"
        blockLoading: true; watchChanges: true
        onFileChanged: reload()
        onSaved: reload()
    }
    function setSave(value: bool): void { savePreference.setText(value ? "on\n" : "off\n"); }
    function dismissError(): void { error = ""; send({op: "clear-error"}); }
    function setEdit(value: bool): void { editorPreference.setText(value ? "on\n" : "off\n"); }

    function start(): void { watcher.running = true; }
    property string recordingSource: ""
    property var send: request => {
        if (commander.running) return false;
        commander.command = ["python3", "-B", backend, "--command", JSON.stringify(request)];
        commander.running = true;
        return true;
    }
    function capture(name: string, mode = "output"): bool {
        if (waiting || capturing || (mode === "output" && !name) || !["output", "region"].includes(mode) || ![0, 3, 5, 10].includes(delay)) return false;
        error = "";
        pending = {output: name, mode, edit, save, hiding: false};
        now = Date.now();
        // DrawerWindow's exit takes 200 ms. Leave a compositor frame margin,
        // including for immediate captures; this timer outlives the lazy page.
        deadline = now + Math.max(400, delay * 1000);
        return true;
    }
    function cancel(): void { pending = null; deadline = 0; }
    function guardDismissal(): void {
        if (recordingPending) { recordingDelay.restart(); hideRequested(); }
        if (regionDelay.running) { regionDelay.restart(); hideRequested(); }
        if (!pending?.hiding) return;
        deadline = Math.max(deadline, Date.now() + 400);
        hideRequested();
    }
    function tick(at = Date.now()): void {
        now = at;
        if (!pending) return;
        // A drawer may have reopened during the countdown. Dismiss it again
        // and allow its exit to finish before starting Hyprshot.
        if (!pending.hiding && at >= deadline - 400) {
            pending = Object.assign({}, pending, {hiding: true});
            deadline = Math.max(deadline, at + 400);
            hideRequested();
            return;
        }
        if (at < deadline) return;
        const request = pending;
        pending = null;
        const command = ["desktop-screenshot", request.mode];
        if (request.mode === "output") command.push("--output", request.output);
        command.push("--report", request.save ? "--save" : "--no-save");
        command.push(request.edit ? "--edit" : "--no-edit");
        grabber.command = command;
        grabber.running = true;
    }
    function record(source = output): bool {
        if (recordingPending || commander.running || !recorder.available) return false;
        if (sessionActive) return send({op: "stop"});
        if (!source) return false;
        error = "";
        recordingSource = source;
        recordingPending = true;
        hideRequested();
        recordingDelay.restart();
        return true;
    }
    function recordRegion(): void {
        if (sessionActive) { send({op: "stop"}); return; }
        if (recordingPending || selector.running || regionDelay.running || commander.running) return;
        hideRequested();
        regionDelay.restart();
    }
    function pauseRecording(): void { send({op: "pause"}); }
    readonly property Timer recordingDelay: Timer {
        interval: 400
        onTriggered: {
            root.hideRequested();
            root.send({op: "start", source: root.recordingSource});
            root.recordingPending = false;
        }
    }
    readonly property Timer regionDelay: Timer {
        interval: 400
        onTriggered: selector.running = true
    }
    readonly property Process selector: Process {
        id: selector
        command: ["slurp", "-f", "%wx%h+%x+%y"]
        property string region: ""
        onStarted: region = ""
        stdout: StdioCollector { onStreamFinished: selector.region = text.trim() }
        stderr: StdioCollector {}
        onExited: (code, status) => { if (code === 0 && region) root.record(region); }
    }
    function setRecordingOption(key: string, value: bool): void {
        if (!sessionActive && !recordingPending) send({op: "option", key, value});
    }
    function updateRecording(line: string): void {
        try {
            const state = JSON.parse(line);
            if (state.phase) recorder = state;
            if (state.error) error = state.error;
        } catch (_) { error = qsTr("Could not read recording status."); }
    }
    readonly property Process commander: Process {
        id: commander
        stdout: SplitParser { onRead: line => root.updateRecording(line) }
        stderr: StdioCollector {}
        onExited: (code, status) => { if (code !== 0) root.error = qsTr("Recording controls unavailable. Check desktop-capture.service."); }
    }
    function openPath(path: string): void { if (path) launch(["xdg-open", path]); }
    function openFolder(kind: string): void {
        if (["pictures", "videos"].includes(kind)) openPath(recorder[kind]);
    }

    readonly property Timer countdown: Timer {
        interval: 100; repeat: true; running: root.waiting
        onTriggered: root.tick()
    }
    readonly property Process grabber: Process {
        id: grabber
        property string image: ""
        property string detail: ""
        onStarted: { image = ""; detail = ""; }
        stdout: StdioCollector { onStreamFinished: grabber.image = text.trim() }
        stderr: StdioCollector { onStreamFinished: grabber.detail = text.trim() }
        onExited: (code, status) => {
            if (code === 0) {
                if (image.startsWith("/")) root.lastImage = image;
            } else root.error = detail || qsTr("Could not take the screenshot. Check that the display is connected and desktop-screenshot is installed.");
        }
    }
    readonly property Process watcher: Process {
        id: watcher
        command: ["python3", "-B", root.backend, "--watch"]
        stdout: SplitParser { onRead: line => root.updateRecording(line) }
        stderr: StdioCollector {}
        onExited: (code, status) => {
            if (code !== 0) root.error = qsTr("Recording controls unavailable. Check desktop-capture.service.");
            reconnect.restart();
        }
    }
    readonly property Timer reconnect: Timer { interval: 5000; onTriggered: watcher.running = true }
}
