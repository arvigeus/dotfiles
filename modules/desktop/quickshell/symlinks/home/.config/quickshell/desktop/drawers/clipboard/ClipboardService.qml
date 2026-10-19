pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    id: root
    property var entries: []
    property bool available: false
    property bool paused: false
    property bool loading: false
    property bool started: false
    property string error: ""
    property var requestQueue: []
    property var thumbnails: ({})
    property var thumbnailPending: ({})

    readonly property string backend: decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, ""))

    function start(): void {
        if (worker.running) return;
        worker.running = true;
        Qt.callLater(() => request({op: "status"}));
    }
    function refresh(): void { request({op: "list"}); }
    function search(query: string): void {
        request({op: "list", query});
    }
    function setPaused(value: bool): void { request({op: "pause", value}); }
    function clear(): void { request({op: "clear"}); }
    function remove(id: int): void { request({op: "delete", id}); }
    function copy(id: int): void { request({op: "copy", id}); }
    function loadThumbnail(id: int): void {
        if (thumbnails[id] || thumbnailPending[id]) return;
        thumbnailPending = Object.assign({}, thumbnailPending, {[id]: true});
        request({op: "thumbnail", id});
    }
    function request(value): void {
        if (!worker.running) start();
        if (value.op === "list" || value.op === "status") loading = true;
        requestQueue = requestQueue.concat([value]);
        pump();
    }
    function pump(): void {
        if (!worker.running || !started || worker.busy || !requestQueue.length) return;
        worker.current = requestQueue[0];
        requestQueue = requestQueue.slice(1);
        worker.busy = true;
        worker.write(JSON.stringify(worker.current) + "\n");
        if (worker.current.op === "list" || worker.current.op === "status") loading = true;
    }
    function receive(line: string): void {
        let result;
        try { result = JSON.parse(line); }
        catch (_) { error = qsTr("Could not read clipboard history."); return; }
        worker.busy = false;
        if (result.op === "error") {
            error = result.error || qsTr("Clipboard history operation failed.");
            loading = requestQueue.some(item => item.op === "list" || item.op === "status");
            if (worker.current.op === "thumbnail") {
                const pending = Object.assign({}, thumbnailPending); delete pending[worker.current.id]; thumbnailPending = pending;
            }
        } else if (result.op === "list" || result.op === "status") {
            available = !!result.available;
            paused = !!result.paused;
            error = result.error || "";
            if (result.op === "list") entries = result.entries || [];
            loading = requestQueue.some(item => item.op === "list" || item.op === "status");
        } else if (result.op === "pause") {
            paused = !!result.paused;
            error = result.error || "";
        } else if (result.op === "clear" || result.op === "delete") {
            error = result.error || "";
            if (!error) refresh();
        } else if (result.op === "copy") {
            error = result.error || "";
            if (!error) copied();
        } else if (result.op === "thumbnail") {
            const pending = Object.assign({}, thumbnailPending); delete pending[result.id]; thumbnailPending = pending;
            const images = Object.assign({}, thumbnails, {[result.id]: result.url});
            for (const expired of result.expired || []) delete images[expired];
            thumbnails = images;
        }
        Qt.callLater(pump);
    }
    signal copied()

    readonly property Process worker: Process {
        id: worker
        property bool busy: false
        property var current: ({})
        command: ["python3", "-B", root.backend]
        stdinEnabled: true
        onStarted: { root.started = true; root.pump(); }
        stdout: SplitParser { onRead: line => root.receive(line) }
        stderr: StdioCollector {}
        onExited: (code, status) => {
            root.started = false;
            busy = false;
            root.loading = false;
            root.available = false;
            root.error = qsTr("Clipboard history service stopped.");
            if (root.requestQueue.length) Qt.callLater(() => root.start());
        }
    }
}
