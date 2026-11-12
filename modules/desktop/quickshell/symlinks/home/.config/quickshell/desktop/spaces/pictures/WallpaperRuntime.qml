import QtQuick
import Quickshell.Io
import Quickshell.Hyprland
import "../movies"

// One session-owned controller. The worker, renderer and portal exist only
// while an animated choice is active or its graceful shutdown is completing.
Item {
    id: root
    visible: false
    property bool animated: false
    property bool stopping: false
    property string selection: ""
    property var screens: []
    readonly property var externalScreens: animated ? screens : []
    property bool pending: false
    property bool refreshAgain: false
    property int generation: 0
    property bool failed: false
    property bool retrying: false
    property int workerRestarts: 0
    property bool configurationReady: false
    property bool ownershipReady: false
    property bool ownershipChecked: false

    Connections {
        target: WallpaperService
        function onChoiceChanged() {
            root.applyChoice();
        }
        function onLoadedChanged() {
            root.applyChoice();
        }
    }
    Component.onCompleted: applyChoice()
    function applyChoice() {
        if (!WallpaperService.loaded)
            return;
        const data = WallpaperService.choice;
        configure(["wallpaper_engine", "video"].includes(data.mode), String(data.selection || ""));
    }

    // Read once at startup: only a journal left by a killed controller matters.
    FileView {
        id: ownership
        path: WallpaperService.configRoot + "/.engine-ownership.json"
        preload: true
        blockLoading: false
        printErrors: false
        onLoaded: {
            root.ownershipReady = true;
            root.reconcileOwnership();
        }
        onLoadFailed: {
            root.ownershipReady = true;
            root.reconcileOwnership();
        }
    }

    function reconcileOwnership() {
        if (!configurationReady || !ownershipReady || ownershipChecked)
            return;
        ownershipChecked = true;
        if (animated || stopping || failed)
            return;
        let data = {};
        try {
            data = JSON.parse(ownership.text());
        } catch (exception) {}
        if (!data?.owner)
            return;
        // A crash followed by a static choice still needs one cleanup worker.
        stopping = true;
        refresh.restart();
    }

    function configure(animated, selection) {
        configurationReady = true;
        Qt.callLater(root.reconcileOwnership);
        if (root.animated === animated && root.selection === selection)
            return;
        generation++;
        root.selection = selection;
        root.stopping = !animated && (root.animated || !!runtime.item || root.retrying);
        root.animated = animated;
        root.failed = false;
        root.retrying = false;
        root.workerRestarts = 0;
        retry.stop();
        screens = [];
        refresh.restart();
    }
    function sync() {
        if (!runtime.item)
            return;
        if (pending) {
            refreshAgain = true;
            return;
        }
        pending = true;
        const requestedGeneration = generation;
        runtime.item.request("sync", {}, (result, error) => {
            pending = false;
            if (requestedGeneration === generation) {
                screens = error || !result ? [] : result.screens || [];
                // Backoff budget covers consecutive worker failures, not a whole session.
                if (!error)
                    workerRestarts = 0;
                if (error || (result && result.error))
                    console.warn("Wallpaper playback:", error || result.error);
                if (!animated && !error)
                    stopping = false;
                if (!animated && error) {
                    stopping = false;
                    failed = true;
                }
                if (animated && error && workerRestarts < 3) {
                    retry.interval = 1000 * Math.pow(2, workerRestarts++);
                    retrying = true;
                    retry.restart();
                } else if (animated && (error || (result && result.error)))
                    failed = true;
            }
            if (refreshAgain || requestedGeneration !== generation) {
                refreshAgain = false;
                refresh.restart();
            }
        });
    }
    Loader {
        id: runtime
        active: (root.animated && !root.failed && !root.retrying) || root.stopping
        sourceComponent: Worker {
            backendDirectory: "spaces/pictures"
            spaceId: "pictures"
            objectName: "wallpaperRuntimeWorker"
            backend: "wallpaper_engine.py"
            // The engine's renderer handoff is designed around SIGKILL on unload.
            gracefulStop: false
            serviceName: "Wallpaper playback"
            onReady: refresh.restart()
        }
    }
    Connections {
        target: Hyprland
        enabled: root.animated && !root.failed && !root.retrying
        function onRawEvent(event) {
            if (["fullscreen", "workspace", "workspacev2", "activespecial", "activespecialv2", "focusedmon", "monitoradded", "monitoraddedv2", "monitorremoved", "configreloaded"].includes(event.name)) {
                refresh.restart();
            }
        }
    }
    Timer {
        id: refresh
        interval: 300
        onTriggered: root.sync()
    }
    Timer {
        id: retry
        onTriggered: {
            root.retrying = false;
            refresh.restart();
        }
    }
    Timer {
        interval: root.screens.length ? 5000 : 1000
        repeat: true
        running: (root.animated && !root.failed && !root.retrying) || root.stopping
        onTriggered: root.sync()
    }
}
