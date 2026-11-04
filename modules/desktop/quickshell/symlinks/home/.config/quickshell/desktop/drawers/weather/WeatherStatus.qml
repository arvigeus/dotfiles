pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import "Conditions.js" as Conditions

// One instance feeds every output's bar, so only one helper runs per poll.
Singleton {
    id: root
    readonly property alias worker: worker
    readonly property alias updates: updates
    readonly property int retryInterval: 300000
    property var snapshot: ({})
    property double lastFailure: 0
    // Wall-clock time of the next helper run. Between forecast expiries the
    // snapshot changes only through weather.json or a drawer fetch, which
    // refresh directly.
    property double nextPoll: 0
    property bool pending: false
    // Saved reminders must run after a reload without opening the drawer.
    readonly property var reminders: ReminderService
    readonly property string temperature: {
        const value = snapshot.weather?.current?.temperature;
        return typeof value === "number" && isFinite(value) ? Conditions.temperature(value) : "";
    }
    readonly property string iconName: snapshot.weather?.current ? Conditions.icon(snapshot.weather.current.code, snapshot.weather.current.isDay) : "cloud"
    readonly property string description: {
        const place = snapshot.location;
        const current = snapshot.weather?.current;
        if (!place)
            return qsTr("Open Time and weather for saved places and forecasts.");
        if (!current)
            return place.name + " · " + qsTr("Weather unavailable. Retrying shortly.");
        const metrics = [];
        if (current.feelsLike != null)
            metrics.push(qsTr("Feels %1").arg(Conditions.temperature(current.feelsLike)));
        if (current.wind != null)
            metrics.push(qsTr("Wind %1 km/h").arg(Math.round(current.wind)));
        if (current.humidity != null)
            metrics.push(qsTr("%1 humidity").arg(Conditions.percent(current.humidity)));
        return [place.name + " · " + Conditions.description(current.code) + " · " + Conditions.temperature(current.temperature) + "C", metrics.join(" · "), snapshot.stale ? qsTr("Outdated · updated %1").arg(snapshot.updated) : qsTr("Updated %1").arg(snapshot.updated)].filter(Boolean).join("\n");
    }
    function refresh(): void {
        if (worker.running) {
            pending = true;
            return;
        }
        worker.stdinEnabled = true;
        worker.running = true;
    }
    Component.onCompleted: refresh()
    FileView {
        id: locationConfig
        path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/desktop/weather.json"
        watchChanges: true
        preload: true
        onFileChanged: {
            reload();
            root.lastFailure = 0;
            root.refresh();
        }
    }
    Timer {
        id: updates
        interval: 60000
        repeat: true
        running: true
        // Wall-clock comparison also catches up promptly after suspend. A run
        // in progress already answers this check; only explicit refreshes queue.
        onTriggered: if (!worker.running && Date.now() >= root.nextPoll)
            root.refresh()
    }
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/weather/backend.py")]
        onStarted: {
            write(JSON.stringify({
                op: "island",
                refresh: Date.now() - root.lastFailure >= root.retryInterval
            }) + "\n");
            stdinEnabled = false;
        }
        stdout: StdioCollector {
            onStreamFinished: {
                if (root.pending)
                    return;
                const now = Date.now();
                try {
                    root.snapshot = JSON.parse(text);
                    if (root.snapshot.error && root.snapshot.due)
                        root.lastFailure = now;
                    else if (!root.snapshot.due)
                        root.lastFailure = 0;
                } catch (_) {
                    root.snapshot = {};
                }
                // Missing places, errors and failed refreshes retry after the backoff.
                root.nextPoll = !root.snapshot.due && root.snapshot.expires > 0 ? root.snapshot.expires * 1000 : now + root.retryInterval;
            }
        }
        stderr: StdioCollector {}
        onExited: if (root.pending) {
            root.pending = false;
            Qt.callLater(root.refresh);
        }
    }
}
