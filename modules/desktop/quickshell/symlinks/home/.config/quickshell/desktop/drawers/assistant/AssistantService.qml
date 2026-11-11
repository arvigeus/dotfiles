pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import "../../ui"

Singleton {
    id: root
    property bool observed: false
    property bool online: false
    property bool installed: true
    property bool checked: false
    property string scope: ""
    property string serverState: "inactive"
    property string url: "http://localhost:13305"
    property var models: []
    property var loaded: []
    property var downloads: []
    property var catalogueGeneration: null
    property var catalogueAliases: ({})
    property string error: ""
    property string saveError: ""
    property string attachmentError: ""
    property var attachments: []
    property var attachmentQueue: []
    property string responseStyle: "default"
    property var preferredThinking: ({})
    property string draft: ""
    property string responseLength: "brief"
    property string preferredModel: ""
    property bool preferencesReady: false
    property bool thinking: false
    property bool cancelling: false
    property bool completed: false
    property string pendingOperation: "status"
    property var pendingRequest: ({
            op: "status"
        })
    property var queuedRequest: null
    readonly property bool checking: control.running || !!queuedRequest
    readonly property bool working: checking && (pendingOperation !== "status" || !!queuedRequest)
    readonly property bool changingServer: working && ["connect", "start", "stop"].includes(pendingOperation)
    readonly property bool generating: generation.running
    readonly property bool preparing: importer.running || attachmentQueue.length > 0
    readonly property bool busy: generating || working || preparing
    readonly property string selectedModel: models.find(row => row.id === preferredModel)?.id || models.find(row => row.downloaded && loaded.some(item => item.id === row.id))?.id || models.find(row => row.downloaded)?.id || (!online ? preferredModel : "")
    readonly property var selectedEntry: models.find(row => row.id === selectedModel) ?? null
    readonly property var selectedLoaded: loaded.find(row => row.id === (selectedEntry?.target || selectedModel)) ?? null
    readonly property var selectedDownload: downloads.find(row => row.model_name === (selectedEntry?.target || selectedModel) && row.status !== "completed") ?? null
    readonly property bool modelAvailable: selectedEntry?.downloaded ?? false
    readonly property bool supportsVision: selectedEntry?.labels?.includes("vision") ?? false
    readonly property string thinkingMode: preferredThinking[selectedModel] || "auto"
    readonly property bool needsVision: {
        if (attachments.some(item => item.kind === "image"))
            return true;
        for (let i = 0; i < history.count; i++)
            if (history.get(i).hasImages)
                return true;
        return false;
    }
    readonly property string attachmentHint: selectedEntry && needsVision && !supportsVision ? qsTr("Choose a vision model for these images, or start a new chat.") : ""
    readonly property int lastUserIndex: history.count && history.get(history.count - 1).speaker === "user" ? history.count - 1 : history.count - 2
    readonly property bool canEditLast: !busy && !draft.trim() && !attachments.length && lastUserIndex >= 0
    readonly property bool downloading: downloads.some(row => row.running)
    readonly property bool serverInUse: loaded.some(row => row.busy)
    readonly property bool canRelease: !!selectedLoaded && !selectedLoaded.busy && !selectedLoaded.pinned && !busy
    readonly property bool canSend: checked && installed && !!selectedModel && (selectedEntry || !online) && !attachmentHint && !busy && (!!draft.trim() || attachments.length > 0) && history.count < 80
    readonly property alias messages: history
    // A reply longer than the context limit could never be sent back.
    readonly property int maximumReply: 160000
    signal appOpened
    signal pasted(int cursor)

    ListModel {
        id: history
    }

    function attachUrls(urls, notify): bool {
        return enqueueImport({
            op: "attach",
            urls: Array.from(urls, value => String(value)),
            notify: !!notify
        });
    }
    function paste(start: int, end: int): void {
        enqueueImport({
            op: "paste",
            start,
            end,
            baseDraft: draft
        });
    }
    function enqueueImport(value): bool {
        if (attachmentQueue.length >= 6) {
            attachmentError = qsTr("Wait for the current files to finish preparing.");
            return false;
        }
        attachmentQueue = attachmentQueue.concat([value]);
        pumpImports();
        return true;
    }
    function pumpImports(): void {
        if (importer.running || !attachmentQueue.length)
            return;
        importer.current = attachmentQueue[0];
        attachmentQueue = attachmentQueue.slice(1);
        attachmentError = "";
        importer.answered = false;
        importer.added = 0;
        importer.active = true;
        importer.running = true;
    }
    // Stored size of a snapshot, without serializing megabytes on the GUI thread.
    function weight(item): int {
        return (item.data || item.text || "").length + (item.name || "").length + 256;
    }
    function acceptFiles(items): void {
        const next = attachments.slice();
        let bytes = next.reduce((total, item) => total + weight(item), 0);
        for (let i = 0; i < history.count; i++)
            bytes += (history.get(i).filesJson || "").length;
        for (const item of items) {
            if (next.some(existing => existing.id === item.id))
                continue;
            if (next.length >= 6 || bytes + weight(item) > 24 * 1024 * 1024 - 200000) {
                attachmentError = qsTr("Attachment limit reached. Use up to six files or start a new chat.");
                break;
            }
            next.push(item);
            bytes += weight(item);
        }
        attachments = next;
    }
    function notify(message: string): void {
        const escaped = message.slice(0, 2000).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        Quickshell.execDetached(["notify-send", "--app-name=Assistant", "--icon=mail-attachment", "Assistant", escaped]);
    }
    function removeAttachment(id: string): void {
        attachments = attachments.filter(item => item.id !== id);
        attachmentError = "";
    }
    function editLast(): bool {
        if (!canEditLast)
            return false;
        const row = history.get(lastUserIndex);
        const text = row.body;
        const files = JSON.parse(row.filesJson || "[]");
        history.remove(lastUserIndex, history.count - lastUserIndex);
        draft = text;
        attachments = files;
        error = "";
        return true;
    }
    function chooseThinking(value: string): void {
        if (busy || !selectedEntry || !["auto", "on", "off"].includes(value))
            return;
        preferredThinking = Object.assign({}, preferredThinking, {
            [selectedModel]: value
        });
        savePreferences();
    }
    function chooseStyle(value: string): void {
        if (!busy && ["default", "precise", "creative"].includes(value)) {
            responseStyle = value;
            savePreferences();
        }
    }

    function refresh(): void {
        if (checking || (generating && modelAvailable))
            return;
        request({
            op: "status",
            generation: catalogueGeneration,
            aliases: catalogueAliases
        });
    }
    function connect(): void {
        if (!busy)
            request({
                op: "connect"
            });
    }
    function request(value): bool {
        if (control.running) {
            if (value.op === "status" || queuedRequest)
                return false;
            queuedRequest = value;
            return true;
        }
        pendingRequest = value;
        pendingOperation = value.op;
        if (value.op !== "status")
            error = "";
        control.answered = false;
        control.result = null;
        control.active = true;
        control.running = true;
        return true;
    }
    function setServer(running: bool): void {
        if (busy || (!running && (downloading || serverInUse)))
            return;
        request({
            op: running ? "connect" : "stop"
        });
    }
    function openApp(): void {
        if (online)
            launchApp();
        else if (!busy && installed)
            request({
                op: "connect",
                intent: "open"
            });
    }
    function launchApp(): void {
        Apps.launch(["lemonade-web-app"]);
        appOpened();
    }
    function downloadModel(value: string): void {
        if (!online || busy || !models.some(row => row.id === value))
            return;
        if (request({
            op: "download",
            model: value
        })) {
            preferredModel = value;
            savePreferences();
        }
    }
    function pauseDownload(value: string): void {
        if (online && !busy)
            request({
                op: "pause",
                model: value
            });
    }
    function releaseModel(): void {
        if (online && canRelease)
            request({
                op: "unload",
                model: selectedModel
            });
    }
    function canDeleteModel(value: string): bool {
        const entry = models.find(row => row.id === value);
        const target = entry?.target || value;
        const model = loaded.find(row => row.id === target);
        return online && !busy && !!entry?.downloaded && !model?.busy && !model?.pinned && !downloads.some(job => job.model_name === target && job.running);
    }
    function deleteModel(value: string): void {
        if (canDeleteModel(value))
            request({
                op: "delete",
                model: value
            });
    }
    function chooseModel(value: string): void {
        if (busy || !models.some(row => row.id === value))
            return;
        preferredModel = value;
        savePreferences();
    }
    function chooseLength(value: string): void {
        if (!["brief", "balanced", "detailed"].includes(value))
            return;
        responseLength = value;
        savePreferences();
    }
    function savePreferences(): void {
        if (preferencesReady)
            preferences.setText(JSON.stringify({
                length: responseLength,
                model: preferredModel,
                style: responseStyle,
                thinking: preferredThinking
            }) + "\n");
    }
    function newChat(): void {
        if (busy)
            return;
        history.clear();
        error = "";
        draft = "";
        attachments = [];
        attachmentError = "";
    }
    function send(): bool {
        if (!canSend)
            return false;
        const prompt = draft.trim() ? draft : (attachments.every(item => item.kind === "image") ? qsTr("Describe the attached images.") : qsTr("Summarize the attached files."));
        if (!online)
            return request({
                op: "connect",
                intent: "send",
                prompt,
                model: selectedModel,
                files: attachments
            });
        sendText(prompt, attachments);
        return true;
    }
    function sendText(prompt: string, files): void {
        history.append({
            speaker: "user",
            body: prompt,
            modelName: "",
            state: "done",
            filesJson: JSON.stringify(files),
            hasImages: files.some(item => item.kind === "image"),
            reasoning: ""
        });
        if (draft === prompt || !draft.trim())
            draft = "";
        attachments = attachments.filter(item => !files.some(sent => sent.id === item.id));
        beginReply();
    }
    function retry(): void {
        if (busy || attachmentHint || !selectedModel || !history.count)
            return;
        if (!online) {
            request({
                op: "connect",
                intent: "retry",
                model: selectedModel
            });
            return;
        }
        if (!selectedEntry)
            return;
        if (history.get(history.count - 1).speaker === "assistant")
            history.remove(history.count - 1);
        beginReply();
    }
    function beginReply(): void {
        if (preferredModel !== selectedModel)
            chooseModel(selectedModel);
        const context = [];
        for (let i = 0; i < history.count; i++) {
            const row = history.get(i);
            if (row.body || row.filesJson && row.filesJson !== "[]")
                context.push({
                    role: row.speaker,
                    content: row.body,
                    attachments: JSON.parse(row.filesJson || "[]")
                });
        }
        generation.payload = {
            op: "chat",
            model: selectedModel,
            length: responseLength,
            thinking: thinkingMode,
            style: responseStyle,
            messages: context
        };
        history.append({
            speaker: "assistant",
            body: "",
            modelName: selectedModel,
            state: "streaming",
            filesJson: "[]",
            hasImages: false,
            reasoning: ""
        });
        thinking = false;
        cancelling = false;
        completed = false;
        error = "";
        generation.active = true;
        generation.running = true;
        if (!modelAvailable)
            Qt.callLater(refresh);
    }
    function cancel(): void {
        if (generating && !cancelling) {
            cancelling = true;
            generation.signal(15);
        }
    }
    function receive(line: string): void {
        if (cancelling || !history.count)
            return;
        try {
            const value = JSON.parse(line);
            const index = history.count - 1;
            if (value.type === "delta") {
                const body = history.get(index).body + (value.text || "");
                history.setProperty(index, "body", body.slice(0, maximumReply));
                if (body.length > maximumReply) {
                    completed = true;
                    history.setProperty(index, "state", "limited");
                    cancelling = true;
                    generation.signal(15);
                    return;
                }
                if (value.reasoning)
                    history.setProperty(index, "reasoning", (history.get(index).reasoning + value.reasoning).slice(0, 64000));
                thinking = !!value.thinking;
            } else if (value.type === "done") {
                completed = true;
                history.setProperty(index, "state", value.limited ? "limited" : "done");
                if (!history.get(index).body) {
                    error = value.limited ? qsTr("The model reached its output limit before answering. Try Thinking → Off, or increase its output/context limit in Lemonade.") : history.get(index).reasoning ? qsTr("The model returned thinking without an answer. Try Thinking → Off and retry.") : qsTr("The model returned no answer. Try again or choose another model.");
                }
            } else if (value.type === "error") {
                error = value.error || qsTr("Lemonade could not answer.");
            }
        } catch (_) {
            error = qsTr("Could not read the Lemonade reply.");
        }
    }

    onObservedChanged: if (observed)
        refresh()
    Timer {
        interval: root.downloading || (root.generating && !root.modelAvailable) ? 1000 : 5000
        repeat: true
        running: !root.checking && !root.preparing && (root.generating ? !root.modelAvailable : root.observed && root.online)
        onTriggered: root.refresh()
    }
    FileView {
        id: preferences
        path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/desktop/assistant.json"
        blockLoading: true
        onLoaded: {
            try {
                const value = JSON.parse(text());
                if (typeof value.model === "string")
                    root.preferredModel = value.model;
                if (["brief", "balanced", "detailed"].includes(value.length))
                    root.responseLength = value.length;
                if (["default", "precise", "creative"].includes(value.style))
                    root.responseStyle = value.style;
                const thinking = {};
                for (const [model, mode] of Object.entries(value.thinking || {}))
                    if (["auto", "on", "off"].includes(mode))
                        thinking[model] = mode;
                root.preferredThinking = thinking;
            } catch (_) {
                root.saveError = qsTr("Could not read Assistant preferences.");
            }
            root.preferencesReady = true;
        }
        onLoadFailed: error => {
            root.preferencesReady = true;
        }
        onSaved: root.saveError = ""
        onSaveFailed: error => {
            root.saveError = qsTr("Could not save Assistant preferences.");
        }
    }
    Process {
        id: importer
        property var current: ({})
        property bool active: false
        property bool answered: false
        property int added: 0
        function finish(): void {
            active = false;
            stdinEnabled = true;
            if (!answered)
                root.attachmentError = qsTr("Could not prepare the attachments.");
            if (current.notify) {
                const summary = added === 1 ? qsTr("File added to Assistant.") : added > 1 ? qsTr("%1 files added to Assistant.").arg(added) : root.attachmentError ? "" : qsTr("Files are already attached to Assistant.");
                root.notify([summary, root.attachmentError].filter(Boolean).join("\n"));
            }
            Qt.callLater(root.pumpImports);
        }
        command: ["python3", Quickshell.shellPath("drawers/assistant/backend.py")]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify(current) + "\n");
            stdinEnabled = false;
        }
        stdout: SplitParser {
            onRead: line => {
                try {
                    const value = JSON.parse(line);
                    importer.answered = true;
                    root.attachmentError = value.error || "";
                    if (value.items) {
                        const previous = root.attachments.length;
                        root.acceptFiles(value.items);
                        importer.added += root.attachments.length - previous;
                    }
                    if (typeof value.text === "string") {
                        const position = root.draft === importer.current.baseDraft ? importer.current.start : root.draft.length;
                        const end = root.draft === importer.current.baseDraft ? importer.current.end : position;
                        root.draft = root.draft.slice(0, position) + value.text + root.draft.slice(end);
                        root.pasted(position + value.text.length);
                    }
                } catch (_) {
                    root.attachmentError = qsTr("Could not read the attached files.");
                }
            }
        }
        stderr: StdioCollector {}
        onExited: finish()
        // A helper that cannot start emits no exited signal.
        onRunningChanged: if (!running && active)
            finish()
    }
    Process {
        id: control
        property bool active: false
        property bool answered: false
        property var result: null
        function finish(): void {
            active = false;
            stdinEnabled = true;
            // An unanswered first check must not leave the page waiting forever.
            root.checked = true;
            if (!answered)
                root.error = qsTr("Could not check the Lemonade service.");
            const action = root.pendingRequest;
            const succeeded = result && result.type !== "error" && result.online;
            const queued = root.queuedRequest;
            root.queuedRequest = null;
            if (!succeeded && action.op === "connect" && !root.error)
                root.error = qsTr("Lemonade did not start. Check its service logs and try again.");
            if (queued)
                Qt.callLater(() => root.request(queued));
            else if (succeeded && action.intent === "open")
                root.launchApp();
            else if (succeeded && ["send", "retry"].includes(action.intent)) {
                if (root.selectedModel !== action.model || !root.selectedEntry)
                    root.error = qsTr("The selected model is no longer available. Choose a model to send your message.");
                else if (action.intent === "retry")
                    root.retry();
                else
                    root.sendText(action.prompt, action.files || []);
            }
        }
        command: ["python3", Quickshell.shellPath("drawers/assistant/backend.py")]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify({
                op: root.pendingRequest.op,
                generation: root.pendingRequest.generation,
                aliases: root.pendingRequest.aliases,
                model: root.pendingRequest.model
            }) + "\n");
            stdinEnabled = false;
        }
        stdout: SplitParser {
            onRead: line => {
                try {
                    const value = JSON.parse(line);
                    control.result = value;
                    control.answered = true;
                    root.checked = true;
                    if (value.type === "error") {
                        root.error = value.error;
                        return;
                    }
                    root.online = !!value.online;
                    root.installed = !!value.installed;
                    root.scope = value.scope || "";
                    root.serverState = value.state || "inactive";
                    root.url = value.url || root.url;
                    if (value.models !== undefined)
                        root.models = value.models;
                    root.loaded = value.loaded || [];
                    root.downloads = value.downloads || [];
                    root.catalogueGeneration = value.generation ?? null;
                    root.catalogueAliases = value.aliases || {};
                    // A health refresh must not erase a failed reply.
                    if (value.error || root.pendingOperation !== "status" || !history.count)
                        root.error = value.error || "";
                } catch (_) {
                    root.error = qsTr("Could not read Lemonade status.");
                }
            }
        }
        stderr: StdioCollector {}
        onExited: finish()
        onRunningChanged: if (!running && active)
            finish()
    }
    Process {
        id: generation
        property var payload: ({})
        property bool active: false
        function finish(): void {
            active = false;
            stdinEnabled = true;
            root.thinking = false;
            if (history.count && !root.completed)
                history.setProperty(history.count - 1, "state", root.cancelling ? "stopped" : "error");
            if (!root.completed && !root.cancelling && !root.error)
                root.error = qsTr("Lemonade disconnected. Try the reply again.");
            // Nobody is watching a reply that outlived the drawer.
            if (!root.observed && !root.cancelling && history.count)
                root.notify(root.completed && !root.error ? qsTr("%1 finished replying.").arg(history.get(history.count - 1).modelName) : qsTr("The reply failed: %1").arg(root.error));
            root.cancelling = false;
        }
        command: ["python3", Quickshell.shellPath("drawers/assistant/backend.py")]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify(payload) + "\n");
            stdinEnabled = false;
        }
        stdout: SplitParser {
            onRead: line => root.receive(line)
        }
        stderr: StdioCollector {}
        onExited: finish()
        onRunningChanged: if (!running && active)
            finish()
    }
}
