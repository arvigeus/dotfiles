import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root
    property string kind: ""
    property string query: ""
    property var filters: ({})
    property bool online: true
    property bool active: false
    property var items: []
    property string warning: ""
    property int revision: 0
    property bool pending: false
    readonly property bool busy: active && (pending || helper.running)

    function reload() {
        revision++;
        items = [];
        warning = "";
        debounce.stop();
        pending = active && !!kind && (!!query || Object.keys(filters).length > 0 || !online);
        if (helper.running)
            helper.signal(15);
        if (pending)
            debounce.restart();
    }
    function launch() {
        if (!pending || helper.running || !active)
            return;
        pending = false;
        helper.epoch = revision;
        helper.payload = {
            kind: kind,
            query: query,
            filters: filters,
            online: online
        };
        helper.complete = false;
        helper.open = true;
        helper.running = true;
    }
    onKindChanged: reload()
    onQueryChanged: reload()
    onFiltersChanged: reload()
    onOnlineChanged: reload()
    onActiveChanged: reload()
    Timer {
        id: debounce
        interval: 300
        onTriggered: root.launch()
    }
    Process {
        id: helper
        property int epoch: -1
        property var payload: ({})
        property bool complete: false
        property bool open: false
        command: ["python3", Quickshell.shellPath("ui/space_search.py")]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify(payload) + "\n");
            stdinEnabled = false;
        }
        function finish() {
            if (!open)
                return;
            open = false;
            stdinEnabled = true;
            if (root.active && epoch === root.revision && !complete)
                root.warning = qsTr("Space search could not finish. Try again.");
            if (!debounce.running)
                Qt.callLater(root.launch);
        }
        stdout: SplitParser {
            onRead: line => {
                if (!root.active || helper.epoch !== root.revision)
                    return;
                try {
                    const value = JSON.parse(line);
                    helper.complete = !!value.complete;
                    if (value.items)
                        root.items = value.items;
                    root.warning = value.error || value.warning || "";
                } catch (_) {
                    root.warning = qsTr("Could not read Space search results.");
                }
            }
        }
        stderr: StdioCollector {}
        onExited: finish()
        onRunningChanged: if (!running && open)
            finish()
    }
}
