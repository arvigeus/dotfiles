pragma Singleton
import QtQuick
import Quickshell
import "../../ui"

Singleton {
    id: root
    readonly property var state: CaptureService.recorder.speech ?? ({
            phase: "idle",
            options: {
                language: "auto",
                mode: "transcribe",
                paste: false,
                model: "small"
            },
            modelReady: false,
            error: "",
            message: ""
        })
    readonly property bool ready: !!CaptureService.recorder.speech
    readonly property string phase: state.phase
    readonly property var options: state.options
    readonly property string error: state.error
    readonly property var languages: state.languages ?? [
        {
            code: "auto",
            name: qsTr("Auto-detect")
        }
    ]
    readonly property var models: state.models ?? []
    readonly property var selectedModel: models.find(model => model.id === options.model) ?? ({
            name: options.model || "Whisper",
            size: ""
        })
    readonly property bool modelReady: !!state.modelReady
    readonly property bool recording: phase === "recording"
    readonly property bool processing: ["stopping", "converting", "transcribing", "delivering"].includes(phase)
    readonly property bool preparing: phase === "preparing"
    readonly property real progress: state.progress ?? -1
    readonly property bool starting: ["start", "resume"].includes(planned)
    readonly property bool pending: !!planned || CaptureService.awaiting > 0 || CaptureService.outbox.length > 0
    readonly property bool active: phase !== "idle" && !preparing
    readonly property bool waitingForMicrophone: phase.startsWith("microphone-")
    readonly property bool canCancel: waitingForMicrophone || ["recording", "stopping", "converting", "transcribing", "preparing"].includes(phase)
    readonly property bool openMicrophoneControls: !!state.openMicrophoneControls
    property bool pasteBlocked: true
    property string planned: ""
    readonly property string description: preparing ? (progress >= 0 ? qsTr("Downloading speech model · %1%").arg(Math.floor(progress)) : qsTr("Downloading speech model…")) : starting ? qsTr("Starting microphone…") : waitingForMicrophone ? qsTr("Waiting for microphone…") : recording ? qsTr("Listening · %1 s · Win+Shift+D to finish").arg(state.elapsed || 0) : phase === "stopping" ? qsTr("Finishing audio…") : phase === "converting" ? qsTr("Reading audio file…") : processing ? qsTr("Transcribing locally…") : ""
    signal hideRequested
    signal microphoneSettingsRequested
    onPhaseChanged: if (phase === "microphone-approved") {
        planned = "resume";
        hideRequested();
        settling.restart();
    }
    onOpenMicrophoneControlsChanged: if (openMicrophoneControls) {
        send("controls-opened");
        microphoneSettingsRequested();
    }
    onPasteBlockedChanged: reportContext()
    onActiveChanged: reportContext()

    function reportContext(): void {
        if (active)
            send("context", {
                blocked: pasteBlocked
            });
    }
    function send(action: string, extra = {}): bool {
        return CaptureService.send(Object.assign({
            op: "speech-" + action
        }, extra));
    }
    function toggle(): bool {
        if (!ready || pending || preparing || processing)
            return false;
        if (waitingForMicrophone) {
            cancel();
            return true;
        }
        if (!recording && options.mode !== "audio" && !modelReady) {
            hideRequested();
            return send("setup");
        }
        planned = recording ? "stop" : "start";
        hideRequested();
        settling.restart();
        return true;
    }
    function setup(): void {
        if (ready && !pending && !active && !preparing) {
            hideRequested();
            send("setup");
        }
    }
    function cancel(): void {
        settling.stop();
        planned = "";
        if (canCancel)
            send("cancel");
    }
    function setOutput(value: string): void {
        if (!pending && !active && !preparing)
            send("output", {
                value
            });
    }
    function setOption(key: string, value): void {
        if (!pending && !active && !preparing)
            send("option", {
                key,
                value
            });
    }
    function guardDismissal(): void {
        if (planned) {
            if (planned)
                settling.restart();
            hideRequested();
        }
    }
    function openPath(path: string): void {
        if (path)
            Apps.launch(["xdg-open", path]);
    }
    Timer {
        id: settling
        interval: 400
        onTriggered: {
            const action = root.planned;
            root.planned = "";
            if (action)
                root.send(action);
        }
    }
}
