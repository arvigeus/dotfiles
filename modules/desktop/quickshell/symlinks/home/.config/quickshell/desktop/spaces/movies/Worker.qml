import QtQuick
import "../../ui"
import Quickshell.Io
import Quickshell

// One owned JSON-lines process per module. Every request settles exactly once.
Item {
    id: root
    visible: false
    required property string backend
    property string backendDirectory: "spaces/movies"
    property string serviceName: "Module"
    property string spaceId: "movies"
    property int timeout: 90000
    property int serial: 0
    property var callbacks: ({})
    property bool stopped: false
    property int pendingCount: 0
    property bool startOnDemand: false
    // Quickshell SIGKILLs a destroyed Process. A forking supervisor turns that
    // into SIGTERM for the backend, so its cleanup still runs on close/reload.
    property bool gracefulStop: true
    property bool processReady: false
    property var startupRequests: []
    signal failed(string message)
    signal ready
    signal workerEvent(var payload)

    function settle(id, result, error, errorCode) {
        const pending = callbacks[id];
        delete callbacks[id];
        if (!pending)
            return;
        pendingCount--;
        try {
            pending.callback(result, error || "", errorCode || "");
        } catch (exception) {
            console.error(serviceName + " response handler failed:", exception);
            failed(serviceName + " could not display that response. Retry the request.");
        }
    }
    function failPending(message) {
        for (const id of Object.keys(callbacks))
            settle(id, null, message);
    }
    function halt() {
        processReady = false;
        startupRequests = [];
        stopped = true;
        failPending(serviceName + " service stopped. Close this module using the X in Spaces, then reopen it.");
    }
    function request(op, args, callback, timeoutMs) {
        const id = ++serial;
        callbacks[id] = {
            callback: callback || function () {},
            deadline: timeoutMs === 0 ? Infinity : Date.now() + (timeoutMs || timeout)
        };
        pendingCount++;
        if (stopped) {
            settle(id, null, serviceName + " service stopped. Close this module using the X in Spaces, then reopen it.");
            return id;
        }
        const line = JSON.stringify(Object.assign({}, args || {}, {
            id: id,
            op: op
        })) + "\n";
        if (processReady)
            worker.write(line);
        else {
            startupRequests.push({
                id: id,
                line: line
            });
            worker.running = true;
        }
        return id;
    }
    Timer {
        interval: 1000
        repeat: true
        running: !root.stopped && root.pendingCount > 0
        onTriggered: {
            const now = Date.now();
            for (const id of Object.keys(root.callbacks))
                if (root.callbacks[id].deadline <= now)
                    root.settle(id, null, root.serviceName + " request timed out. Try again.");
        }
    }
    Process {
        id: worker
        // timeout 0 forks, waits and forwards SIGTERM; the backend's parent-death
        // signal fires when timeout itself is killed.
        command: (root.gracefulStop ? ["timeout", "0", "setpriv", "--pdeathsig", "TERM", "--"] : []).concat(["env", "QUICKSHELL_MEDIA_SPACE=" + root.spaceId, "python3", "-u", Quickshell.shellPath(root.backendDirectory + "/" + root.backend)])
        running: !root.startOnDemand
        onStarted: {
            root.processReady = true;
            const requests = root.startupRequests;
            root.startupRequests = [];
            for (const request of requests)
                if (root.callbacks[request.id])
                    worker.write(request.line);
            root.ready();
        }
        stdinEnabled: true
        stderr: SplitParser {
            // A Python traceback spans many lines; warn once per two-second burst.
            property double warnedAt: 0

            onRead: data => {
                const now = Date.now();
                if (now - warnedAt < 2000)
                    return;
                warnedAt = now;
                console.warn(root.serviceName + " helper reported an error");
            }
        }
        stdout: SplitParser {
            onRead: data => {
                if (!String(data).trim())
                    return;
                let response;
                try {
                    response = JSON.parse(data);
                    if (!response)
                        throw new Error("missing response");
                    if (response.event !== undefined) {
                        root.workerEvent(response.event);
                        return;
                    }
                    if (response.id === undefined)
                        throw new Error("missing response id");
                } catch (exception) {
                    const message = root.serviceName + " returned an unreadable response. Retry the request.";
                    root.failPending(message);
                    root.failed(message);
                    return;
                }
                root.settle(response.id, response.result, response.error, response.error_code);
            }
        }
        onExited: root.halt()
        // A process that never starts (missing executable) emits no exited.
        onRunningChanged: if (!running && !root.processReady && !root.stopped)
            root.halt()
    }
    // Under the supervisor, destruction alone delivers exactly one SIGTERM.
    Component.onDestruction: if (!gracefulStop)
        worker.running = false
}
