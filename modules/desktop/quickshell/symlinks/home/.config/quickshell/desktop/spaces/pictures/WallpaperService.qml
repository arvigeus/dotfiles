pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import "../movies"

Singleton {
    id: root
    property bool busy: false
    property string error: ""
    property string message: ""
    property int revision: 0
    property var choice: ({})
    readonly property string configRoot: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/desktop/spaces/pictures"
    readonly property string stillPath: (Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share") + "/quickshell/desktop/spaces/pictures/current-wallpaper"
    readonly property url image: choice.image ? "file://" + stillPath + "?v=" + revision : ""
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
        });
    }
    FileView {
        id: setting
        path: root.configRoot + "/wallpaper.json"
        preload: true
        printErrors: false
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            try {
                root.choice = JSON.parse(text());
            } catch (_) {
                root.choice = ({});
            }
            root.revision++;
        }
        onLoadFailed: root.choice = ({})
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
