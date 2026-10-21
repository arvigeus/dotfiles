import QtQuick
import "."

ShellButton {
    id: root
    property string hint: ""
    property int holdDuration: 1300
    property real progress: 0
    property bool fired: false
    property bool armed: true
    signal confirmed()
    function cancel(): void { hold.stop(); fill.stop(); progress = 0; }
    onPressed: {
        cancel(); fired = false;
        if (enabled && armed && visible) { hold.start(); fill.start(); }
    }
    onReleased: cancel()
    onCanceled: cancel()
    onDownChanged: if (!down) cancel()
    onEnabledChanged: if (!enabled) cancel()
    onVisibleChanged: if (!visible) cancel()
    onArmedChanged: cancel()
    onActiveFocusChanged: if (!activeFocus) cancel()
    Timer {
        id: hold; interval: root.holdDuration
        onTriggered: if (root.down && root.enabled && root.visible && root.armed && !root.fired) {
            root.fired = true; root.cancel(); root.confirmed();
        }
    }
    NumberAnimation { id: fill; target: root; property: "progress"; from: 0; to: 1; duration: root.holdDuration }
    background: ButtonBackground {
        idleColor: root.idleColor; highlighted: root.highlighted; pressed: root.down
        Rectangle { anchors.left: parent.left; anchors.bottom: parent.bottom; width: parent.width * root.progress; height: 3; radius: 1; color: Theme.danger }
    }
    PassiveToolTip { target: root; text: [root.hint, qsTr("Hold for %1 seconds to confirm. Release early to cancel.").arg((root.holdDuration / 1000).toLocaleString(Qt.locale(), "f", 1))].filter(Boolean).join("\n") }
}
