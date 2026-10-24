import QtQuick
import "../../ui"
import Quickshell.Io
import Quickshell

// One owned JSON-lines process per module. Every request settles exactly once.
Item {
    id: root
    visible: false
    required property string backend
    property string serviceName: "Module"
    property int timeout: 90000
    property int serial: 0
    property var callbacks: ({})
    property bool stopped: false
    property int pendingCount: 0
    property bool startOnDemand: false
    property bool processReady: false
    property var startupRequests: []
    signal failed(string message)
    signal ready()

    function settle(id, result, error, errorCode) {
        const pending = callbacks[id];
        delete callbacks[id];
        if (!pending) return;
        pendingCount--;
        try { pending.callback(result, error || "", errorCode || ""); }
        catch (exception) {
            console.error(serviceName + " response handler failed:", exception);
            failed(serviceName + " could not display that response. Retry the request.");
        }
    }
    function failPending(message) {
        for (const id of Object.keys(callbacks)) settle(id, null, message);
    }
    function request(op, args, callback, timeoutMs) {
        const id = ++serial;
        callbacks[id] = {callback: callback || function() {},
                         deadline: timeoutMs === 0 ? Infinity : Date.now() + (timeoutMs || timeout)};
        pendingCount++;
        if (stopped) {
            settle(id, null, serviceName + " service stopped. Close this module using the X in Spaces, then reopen it.");
            return id;
        }
        const line = JSON.stringify(Object.assign({}, args || {}, {id: id, op: op})) + "\n";
        if (processReady) worker.write(line);
        else {
            startupRequests.push({id: id, line: line});
            worker.running = true;
        }
        return id;
    }
    Timer {
        interval: 1000; repeat: true; running: !root.stopped && root.pendingCount > 0
        onTriggered: {
            const now = Date.now();
            for (const id of Object.keys(root.callbacks))
                if (root.callbacks[id].deadline <= now)
                    root.settle(id, null, root.serviceName + " request timed out. Try again.");
        }
    }
    Process {
        id: worker
        command: ["python3", "-u", Quickshell.shellPath("spaces/movies/" + root.backend)]
        running: !root.startOnDemand
        onStarted: {
            root.processReady = true;
            const requests = root.startupRequests;
            root.startupRequests = [];
            for (const request of requests)
                if (root.callbacks[request.id]) worker.write(request.line);
            root.ready();
        }
        stdinEnabled: true
        stderr: SplitParser { onRead: data => console.warn(root.serviceName + " helper reported an error") }
        stdout: SplitParser {
            onRead: data => {
                if (!String(data).trim()) return;
                let response;
                try {
                    response = JSON.parse(data);
                    if (!response || response.id === undefined) throw new Error("missing response id");
                } catch (exception) {
                    const message = root.serviceName + " returned an unreadable response. Retry the request.";
                    root.failPending(message);
                    root.failed(message);
                    return;
                }
                root.settle(response.id, response.result, response.error, response.error_code);
            }
        }
        onExited: {
            root.processReady = false;
            root.startupRequests = [];
            root.stopped = true;
            root.failPending(root.serviceName + " service stopped. Close this module using the X in Spaces, then reopen it.");
        }
    }
    Component.onDestruction: worker.running = false
}
