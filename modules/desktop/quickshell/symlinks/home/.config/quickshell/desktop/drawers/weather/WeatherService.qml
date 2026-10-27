import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: root
    readonly property alias clockTimer: clockTimer
    readonly property alias fetcher: fetcher
    readonly property alias reader: reader
    property bool active: false
    property string selectedId: ""
    property int revision: 0
    property double lastAttempt: 0
    property double clockMinute: Math.floor(Date.now() / 60000)
    property bool pending: false
    property bool statusFailed: false
    property bool freshSelection: true
    property string error: ""
    property var state: ({
            locations: [],
            location: null,
            clock: "",
            date: "",
            zone: "",
            weather: null,
            due: false,
            stale: false,
            updated: ""
        })
    readonly property bool loading: fetcher.running
    readonly property string backend: Quickshell.shellPath("drawers/weather/backend.py")

    function select(id: string): void {
        if (id === selectedId)
            return;
        selectedId = id;
        revision++;
        lastAttempt = 0;
        error = "";
        freshSelection = true;
        // Clear the previous place immediately, including during a slow response.
        state = Object.assign({}, state, {
            location: null,
            clock: "",
            date: "",
            zone: "",
            weather: null,
            updated: "",
            stale: false
        });
        fetcher.running = false;
        refresh();
    }
    function refresh(): void {
        if (!active)
            return;
        pending = true;
        pump();
    }
    function pump(): void {
        if (!active || reader.running || !pending)
            return;
        pending = false;
        reader.request = {
            op: "status",
            id: selectedId
        };
        reader.revision = revision;
        reader.stdinEnabled = true;
        reader.running = true;
    }
    function fetchWeather(force = false): void {
        if (!active || !state.location || fetcher.running || (!force && Date.now() - lastAttempt < 300000))
            return;
        lastAttempt = Date.now();
        error = "";
        fetcher.request = {
            op: "fetch",
            id: state.location.id,
            force
        };
        fetcher.revision = revision;
        fetcher.stdinEnabled = true;
        fetcher.running = true;
    }
    function receive(text: string, token: int, fetched: bool): void {
        if (!active || token !== revision)
            return;
        try {
            const result = JSON.parse(text);
            if (result.locations) {
                if (freshSelection && result.due) {
                    result.weather = null;
                    result.updated = "";
                    result.stale = false;
                } else if (result.weather)
                    freshSelection = false;
                state = result;
                selectedId = result.location?.id ?? "";
                if (result.error)
                    error = result.error;
                else if (fetched || statusFailed)
                    error = "";
                statusFailed = false;
                // A local read started before this successful fetch must not
                // replace it with an older cached snapshot.
                if (fetched)
                    revision++;
            } else {
                error = result.error || qsTr("Could not read weather.");
                statusFailed = !fetched;
            }
            if (!fetched && result.due)
                Qt.callLater(() => fetchWeather());
        } catch (_) {
            error = qsTr("Could not read weather.");
        }
    }
    onActiveChanged: {
        if (active)
            refresh();
        else {
            revision++;
            pending = false;
            reader.running = false;
            fetcher.running = false;
        }
    }
    Timer {
        id: clockTimer
        interval: 1000
        repeat: true
        running: root.active
        onTriggered: {
            const minute = Math.floor(Date.now() / 60000);
            if (minute !== root.clockMinute) {
                root.clockMinute = minute;
                root.refresh();
            }
        }
    }
    Process {
        id: reader
        property var request: ({})
        property int revision: 0
        command: ["python3", root.backend]
        onStarted: {
            write(JSON.stringify(request) + "\n");
            stdinEnabled = false;
        }
        stdout: StdioCollector {
            onStreamFinished: root.receive(text, reader.revision, false)
        }
        stderr: StdioCollector {}
        onExited: Qt.callLater(root.pump)
    }
    Process {
        id: fetcher
        property var request: ({})
        property int revision: 0
        command: ["python3", root.backend]
        onStarted: {
            write(JSON.stringify(request) + "\n");
            stdinEnabled = false;
        }
        stdout: StdioCollector {
            onStreamFinished: root.receive(text, fetcher.revision, true)
        }
        stderr: StdioCollector {}
        onExited: if (root.active && revision !== root.revision)
            root.refresh()
    }
}
