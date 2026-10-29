pragma Singleton
import QtQuick
import QtCore
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire
import "../../ui/AudioIcons.js" as AudioIcons

// Levels, mute, defaults and application streams are native PipeWire objects.
// backend.py supplies the device inventory (labels, routes, profiles) and runs
// the card, route and stream-move actions that Quickshell cannot perform.
Singleton {
    id: root
    property var observers: []
    readonly property bool observing: observers.length > 0
    property bool loaded: false
    property string error: ""
    property bool readFailed: false
    // The watcher exit was requested (dismissal or refresh), so it is not a failure.
    // Observation can resume before that exit; Process then restarts the watcher.
    property bool stopping: false
    property var boosts: ({})
    property var state: ({
            available: false,
            outputs: [],
            outputDevices: [],
            inputs: [],
            inputDevices: [],
            warning: ""
        })
    property var queue: []
    property var request: null
    property bool received: false
    readonly property bool busy: request !== null
    readonly property string defaultSink: Pipewire.defaultAudioSink?.name ?? ""
    readonly property string defaultSource: Pipewire.defaultAudioSource?.name ?? ""
    // Hardware and virtual endpoints by node.name, the inventory key.
    readonly property var nodes: {
        const map = {};
        for (const node of Pipewire.nodes.values)
            if (node.audio && !node.isStream)
                map[node.name] = node;
        return map;
    }
    readonly property var streams: records(true, Pipewire.nodes.values, Pipewire.linkGroups.values)
    readonly property var recordings: records(false, Pipewire.nodes.values, Pipewire.linkGroups.values)
    // Test hooks for the helper processes.
    readonly property alias watcher: watcher
    readonly property alias worker: worker

    Settings {
        id: preferences
        location: StandardPaths.writableLocation(StandardPaths.ConfigLocation) + "/quickshell/desktop/audio.ini"
        category: "Playback"
    }
    Component.onCompleted: {
        try {
            const saved = JSON.parse(preferences.value("boostDevices", "{}"));
            const restored = {};
            if (saved && typeof saved === "object" && !Array.isArray(saved))
                for (const key of Object.keys(saved))
                    if (saved[key] === true)
                        restored[key] = true;
            boosts = restored;
        } catch (_) {
            boosts = {};
        }
    }

    // Application streams, excluding the drawer's own test client. Playback
    // streams are sinks in Quickshell's model (they accept audio for output).
    // Capturing a sink monitor or another stream records output, not a microphone.
    function records(playback: bool, nodes: var, links: var): var {
        const linkFor = node => links.find(group => playback ? group.source === node : group.target === node);
        return nodes.filter(node => node.audio && node.isStream && node.isSink === playback && node.ready && node.properties["application.id"] !== "dotfiles.audio-test" && (playback || !linkFor(node)?.source?.isSink)).map(node => {
            const props = node.properties;
            const link = linkFor(node);
            const device = playback ? link?.target : link?.source;
            return {
                key: String(props["object.serial"] ?? node.id),
                serial: Number(props["object.serial"] ?? -1),
                node,
                label: props["application.name"] || props["media.name"] || node.description || node.name || qsTr("Audio application"),
                detail: props["media.name"] ?? "",
                icon: props["application.icon-name"] ?? props["application.icon_name"] ?? "",
                applicationId: props["application.id"] ?? "",
                applicationBinary: props["application.process.binary"] ?? "",
                target: device?.name ?? "",
                active: link?.state === PwLinkState.Active
            };
        }).sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase()) || a.key.localeCompare(b.key));
    }
    // Percent of the loudest channel, as the bar shows; changes preserve balance.
    function level(node): real {
        return AudioIcons.level(node?.audio);
    }
    function setLevel(node, percent: real): void {
        const audio = node?.audio;
        if (!audio)
            return;
        const target = Math.max(0, percent) / 100;
        const volumes = Array.from(audio.volumes);
        const peak = volumes.length ? Math.max(...volumes) : 0;
        if (peak > 0)
            audio.volumes = volumes.map(value => value * target / peak);
        else
            audio.volume = target;
    }
    function cap(node, percent: real): void {
        if (node?.audio && level(node) > percent)
            setLevel(node, percent);
    }
    function setMuted(node, muted: bool): void {
        if (node?.audio)
            node.audio.muted = muted;
    }
    function setDefault(node): void {
        if (!node)
            return;
        if (node.isSink)
            Pipewire.preferredDefaultAudioSink = node;
        else
            Pipewire.preferredDefaultAudioSource = node;
    }
    function boostFor(device: string): bool {
        return boosts[device] === true;
    }
    // Turning boost off immediately caps the device's outputs and their apps.
    function setBoost(device: string, enabled: bool): void {
        if (!enabled) {
            for (const output of state.outputs.filter(output => output.deviceKey === device)) {
                cap(nodes[output.name], Math.min(100, output.maxVolume));
                for (const stream of streams.filter(stream => stream.target === output.name))
                    cap(stream.node, 100);
            }
        }
        const next = Object.assign({}, boosts);
        if (enabled)
            next[device] = true;
        else
            delete next[device];
        boosts = next;
        preferences.setValue("boostDevices", JSON.stringify(next));
        preferences.sync();
    }
    function move(stream, destination): void {
        const playback = stream.node?.isSink ?? true;
        if (playback && !boostFor(destination.deviceKey))
            cap(stream.node, 100);
        run("move", {
            kind: playback ? "stream" : "recording",
            serial: stream.serial,
            destination: destination.name
        });
    }
    function observe(owner, active: bool): void {
        observers = observers.filter(item => item !== owner).concat(active ? [owner] : []);
    }
    function run(op: string, values = {}): void {
        error = "";
        queue = queue.concat([Object.assign({
                op
            }, values)]);
        pump();
    }
    function refresh(): void {
        error = "";
        if (watcher.running) {
            stopping = true;
            watcher.signal(15);
        } else
            watcher.running = observing;
    }
    function pump(): void {
        if (worker.running || request || !queue.length)
            return;
        request = queue[0];
        queue = queue.slice(1);
        received = false;
        worker.running = true;
    }
    function fail(message: string): void {
        error = message;
        loaded = true;
        readFailed = true;
        state = {
            available: false,
            outputs: [],
            outputDevices: [],
            inputs: [],
            inputDevices: [],
            warning: ""
        };
    }
    onObservingChanged: {
        if (!observing && watcher.running)
            stopping = true;
        watcher.running = observing;
    }

    PwObjectTracker {
        objects: root.observing ? Pipewire.nodes.values.filter(node => node.audio).concat(Pipewire.linkGroups.values.filter(group => group.source?.isStream || group.target?.isStream)) : []
    }
    Process {
        id: watcher
        command: ["python3", Quickshell.shellPath("drawers/audio/backend.py"), "watch"]
        stdout: SplitParser {
            onRead: line => {
                try {
                    const result = JSON.parse(line);
                    root.loaded = true;
                    if (!result.ok) {
                        root.fail(result.error || qsTr("Could not read audio status. Refresh to retry."));
                        return;
                    }
                    root.state = result.data;
                    if (root.readFailed) {
                        root.error = "";
                        root.readFailed = false;
                    }
                } catch (_) {
                    root.fail(qsTr("Could not read audio status. Refresh to retry."));
                }
            }
        }
        stderr: StdioCollector {}
        onExited: {
            if (root.stopping) {
                root.stopping = false;
                running = root.observing;
            } else if (root.observing)
                root.fail(qsTr("Audio helper stopped. Refresh to retry."));
        }
    }
    Process {
        id: worker
        command: ["python3", Quickshell.shellPath("drawers/audio/backend.py")]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify(root.request) + "\n");
            stdinEnabled = false;
        }
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text);
                    root.received = true;
                    if (!result.ok)
                        root.error = result.error || qsTr("Audio change failed.");
                } catch (_) {
                    root.error = qsTr("Audio change failed. Refresh to retry.");
                }
            }
        }
        stderr: StdioCollector {}
        onExited: {
            if (!root.received && !root.error)
                root.error = qsTr("Audio helper stopped. Refresh to retry.");
            root.request = null;
            stdinEnabled = true;
            Qt.callLater(root.pump);
        }
    }
}
