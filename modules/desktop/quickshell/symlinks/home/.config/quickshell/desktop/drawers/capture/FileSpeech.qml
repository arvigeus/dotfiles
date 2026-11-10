import QtQuick

// A file job belongs to the service and can be recovered after closing a Space.
Item {
    id: root
    visible: false
    required property string path
    readonly property var state: CaptureService.recorder.speech || ({})
    readonly property bool available: !!state.fileOutputs?.includes("srt")
    readonly property bool working: !!path && state.source === path && state.output === "srt" && state.phase !== "idle"
    readonly property bool busy: !!state.phase && state.phase !== "idle"
    readonly property string description: working ? state.phase === "preparing" ? qsTr("Downloading speech model…") : state.phase === "converting" ? qsTr("Reading audio…") : qsTr("Generating subtitles…") : ""
    readonly property string modelName: (state.models || []).find(model => model.id === state.options?.model)?.name || "Whisper"
    readonly property string languageName: (state.languages || []).find(language => language.code === state.options?.language)?.name || qsTr("Auto-detect")
    property string requestedId: ""
    property string observedId: ""
    property string settledId: ""
    signal completed(string message)
    signal failed(string message)

    function generate(): void {
        if (!path || busy || requestedId)
            return;
        requestedId = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
        CaptureService.send({
            op: "speech-file",
            path: path,
            output: "srt",
            jobId: requestedId
        });
    }
    function cancel(): void {
        if (working)
            CaptureService.send({
                op: "speech-cancel",
                jobId: state.jobId
            });
    }
    function observe(): void {
        if (working)
            observedId = state.jobId;
        if (requestedId && state.jobId === requestedId) {
            observedId = requestedId;
            requestedId = "";
        }
        const result = state.result;
        if (state.phase === "idle" && result?.id && result.id === observedId && result.id !== settledId) {
            settledId = result.id;
            if (result.status === "error")
                failed(result.error);
            else
                completed(result.path ? qsTr("Saved %1").arg(result.path.split("/").pop()) : result.message || qsTr("Cancelled."));
        }
    }
    onStateChanged: observe()
    onPathChanged: {
        observedId = "";
        requestedId = "";
        observe();
    }
    Connections {
        target: CaptureService
        function onRecorderChanged() {
            if (CaptureService.recorder.reply && CaptureService.recorder.requestError && CaptureService.recorder.requestJobId && (CaptureService.recorder.requestJobId === root.requestedId || (CaptureService.recorder.requestJobId === root.state.jobId && root.state.source === root.path))) {
                root.requestedId = "";
                root.failed(CaptureService.recorder.requestError);
            }
        }
    }
    Component.onCompleted: {
        CaptureService.start();
        observe();
    }
}
