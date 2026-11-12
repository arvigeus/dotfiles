pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import "../movies"

// The shell's single reader of the saved wallpaper choice.
Singleton {
    id: root
    property bool busy: false
    property string error: ""
    property string message: ""
    property int revision: 0
    property var choice: ({})
    // True once the first read finished, including a missing or unreadable file.
    property bool loaded: false
    // Apply waits for bounded downloads, startup and shutdown (about 3.5 minutes at worst).
    readonly property int applyTimeout: 240000
    readonly property string configRoot: xdgHome("XDG_CONFIG_HOME", "/.config") + "/quickshell/desktop/spaces/pictures"
    readonly property string stillPath: xdgHome("XDG_DATA_HOME", "/.local/share") + "/quickshell/desktop/spaces/pictures/current-wallpaper"
    readonly property url image: choice.image ? "file://" + stillPath + "?v=" + revision : ""
    // Relative XDG values are invalid and ignored, as in the Python helpers.
    function xdgHome(name, fallback) {
        const value = Quickshell.env(name) || "";
        return value.startsWith("/") ? value : Quickshell.env("HOME") + fallback;
    }
    function randomWallhaven() {
        if (busy)
            return;
        busy = true;
        error = "";
        message = "";
        action.active = true;
        action.item.request("randomSet", {}, (result, failure) => {
            busy = false;
            error = failure;
            message = failure ? "" : (result?.message || "");
            action.active = false;
        }, applyTimeout);
    }
    FileView {
        id: setting
        path: root.configRoot + "/wallpaper.json"
        preload: true
        printErrors: false
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            let value = null;
            try {
                value = JSON.parse(text());
            } catch (_) {}
            root.choice = value && typeof value === "object" && !Array.isArray(value) ? value : ({});
            root.revision++;
            root.loaded = true;
        }
        onLoadFailed: {
            root.choice = ({});
            root.loaded = true;
        }
    }
    Loader {
        id: action
        active: false
        sourceComponent: Worker {
            backend: "backend.py"
            backendDirectory: "spaces/pictures"
            spaceId: "pictures"
            serviceName: "Wallpaper"
            startOnDemand: true
        }
    }
}
