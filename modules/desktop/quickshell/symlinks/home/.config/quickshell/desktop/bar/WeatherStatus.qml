import QtQuick
import Quickshell
import Quickshell.Io
import "../drawers/weather/Conditions.js" as Conditions

QtObject {
    id: root
    property var snapshot: ({})
    property double lastFailure: 0
    property bool pending: false
    readonly property string temperature: {
        const value = snapshot.weather?.current?.temperature;
        return typeof value === "number" && isFinite(value) ? Conditions.temperature(value) : "";
    }
    readonly property string iconName: snapshot.weather?.current
        ? Conditions.icon(snapshot.weather.current.code, snapshot.weather.current.isDay) : "cloud"
    readonly property string description: {
        const place = snapshot.location;
        const current = snapshot.weather?.current;
        if (!place) return qsTr("Open Time and weather for saved places and forecasts.");
        if (!current) return place.name + " · " + qsTr("Weather unavailable. Retrying shortly.");
        const metrics = [];
        if (current.feelsLike != null) metrics.push(qsTr("Feels %1").arg(Conditions.temperature(current.feelsLike)));
        if (current.wind != null) metrics.push(qsTr("Wind %1 km/h").arg(Math.round(current.wind)));
        if (current.humidity != null) metrics.push(qsTr("%1 humidity").arg(Conditions.percent(current.humidity)));
        return [place.name + " · " + Conditions.description(current.code) + " · " + Conditions.temperature(current.temperature) + "C",
            metrics.join(" · "),
            snapshot.stale ? qsTr("Outdated · updated %1").arg(snapshot.updated) : qsTr("Updated %1").arg(snapshot.updated)].filter(Boolean).join("\n");
    }
    function refresh(): void {
        if (worker.running) { pending = true; return; }
        worker.stdinEnabled = true; worker.running = true;
    }
    Component.onCompleted: refresh()
    readonly property FileView locationConfig: FileView {
        path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/desktop/weather.json"
        watchChanges: true; preload: true
        onFileChanged: { reload(); root.lastFailure = 0; root.refresh(); }
    }
    readonly property Timer updates: Timer { interval: 60000; repeat: true; running: true; onTriggered: root.refresh() }
    readonly property Process worker: Process {
        command: ["python3", "-B", decodeURIComponent(Qt.resolvedUrl("../drawers/weather/backend.py").toString().replace(/^file:\/\//, ""))]
        onStarted: { write(JSON.stringify({op: "island", refresh: Date.now() - root.lastFailure >= 300000}) + "\n"); stdinEnabled = false; }
        stdout: StdioCollector {
            onStreamFinished: {
                if (root.pending) return;
                try {
                    root.snapshot = JSON.parse(text);
                    if (root.snapshot.error && root.snapshot.due) root.lastFailure = Date.now();
                    else if (!root.snapshot.due) root.lastFailure = 0;
                }
                catch (_) { root.snapshot = {}; }
            }
        }
        stderr: StdioCollector {}
        onExited: if (root.pending) { root.pending = false; Qt.callLater(root.refresh); }
    }
}
