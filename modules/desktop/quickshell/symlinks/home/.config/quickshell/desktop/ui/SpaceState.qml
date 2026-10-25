pragma Singleton
import QtQuick
import Quickshell

Singleton {
    id: root
    property var host: null
    property string currentId: ""
    property var runningIds: []
    readonly property var entries: [
        { id: "pictures", name: qsTr("Pictures"), icon: "image", source: "../spaces/pictures/Main.qml" },
        {
            id: "movies",
            name: qsTr("Movies"),
            icon: "film",
            source: "../spaces/movies/MediaBrowser.qml"
        },
        {
            id: "series",
            name: qsTr("TV Series"),
            icon: "tv",
            source: "../spaces/series/Main.qml"
        },
        {
            id: "games",
            name: qsTr("Games"),
            icon: "gamepad-2",
            source: "../spaces/games/Main.qml"
        }
    ]

    function open(id, output, payload) {
        if (!host || !entries.some(entry => entry.id === id))
            return false;
        const screen = output || host.focusedOutput();
        if (!Quickshell.screens.includes(screen))
            return false;
        if (!runningIds.includes(id))
            runningIds = runningIds.concat([id]);
        currentId = id;
        host.openOn(screen);
        host.deliver(id, payload);
        return true;
    }
    function hide() {
        if (host)
            host.dismiss();
    }
    function close(id) {
        if (currentId === id) {
            hide();
            currentId = "";
        }
        runningIds = runningIds.filter(value => value !== id);
    }
}
