import QtQuick

QtObject {
    id: root
    property bool active: false
    property bool ready: false
    property var payload: null
    signal delivered(var value)
    function submit(value) {
        payload = value;
    }
    function schedule() {
        delivery.stop();
        if (active && ready && payload !== null)
            delivery.start();
    }
    onPayloadChanged: schedule()
    onReadyChanged: schedule()
    onActiveChanged: {
        if (!active)
            payload = null;
        schedule();
    }
    property Timer delivery: Timer {
        interval: 0
        onTriggered: {
            if (!root.active || !root.ready || root.payload === null)
                return;
            const value = root.payload;
            root.payload = null;
            root.delivered(value);
        }
    }
}
