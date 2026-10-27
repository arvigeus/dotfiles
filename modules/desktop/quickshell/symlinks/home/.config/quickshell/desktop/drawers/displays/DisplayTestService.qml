pragma Singleton
import QtQuick
import Quickshell

Scope {
    id: root
    property url windowSource: Qt.resolvedUrl("DisplayTestWindow.qml")
    property string mode: ""
    property string error: ""
    property var targets: []
    property int generation: 0
    readonly property bool running: mode !== ""
    function stop(): void {
        identifyTimer.stop();
        generation++;
        mode = "";
        targets = [];
    }
    function identify(records): bool {
        stop();
        error = "";
        const next = records.filter(record => record.enabled).map((record, index) => ({
                    screen: Quickshell.screens.find(screen => screen.name === record.name),
                    record,
                    number: index + 1,
                    generation: root.generation
                })).filter(target => target.screen);
        if (!next.length) {
            error = qsTr("No enabled displays are available to identify.");
            return false;
        }
        mode = "identify";
        targets = next;
        identifyTimer.restart();
        return true;
    }
    function start(kind: string, record): bool {
        stop();
        error = "";
        const screen = Quickshell.screens.find(screen => screen.name === record.name);
        if (!record.enabled || !screen) {
            error = qsTr("This display is no longer available.");
            return false;
        }
        if (!["patterns", "motion"].includes(kind)) {
            error = qsTr("Unknown display test.");
            return false;
        }
        mode = kind;
        targets = [
            {
                screen,
                record,
                number: 1,
                generation: root.generation
            }
        ];
        return true;
    }
    function reconcile(screens = Quickshell.screens): void {
        const next = targets.filter(target => screens.includes(target.screen));
        if (!next.length)
            stop();
        else if (next.length !== targets.length)
            targets = next;
    }
    Connections {
        target: Quickshell
        function onScreensChanged(): void {
            root.reconcile();
        }
    }
    Timer {
        id: identifyTimer
        interval: 5000
        onTriggered: root.stop()
    }
    Variants {
        model: root.targets
        delegate: LazyLoader {
            required property var modelData
            // Variants defers removal; old delegates must not reload when a
            // replacement test starts in the same event-loop turn.
            active: root.running && modelData.generation === root.generation
            source: root.windowSource
            onItemChanged: if (item) {
                item.target = modelData;
                item.controller = root;
            }
        }
    }
}
