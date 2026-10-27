import "../../ui"
import QtQuick
import QtQuick.Controls

Button {
    id: root

    required property var tester
    property bool microphone: false
    property bool canStart: false
    property string targetLabel: ""
    property bool held: false
    property bool cancelOnClick: false
    readonly property string detail: tester.error || tester.detail || targetLabel
    readonly property bool recording: tester.phase === "recording" || tester.phase === "ready"

    implicitHeight: detail ? 64 : 48
    padding: 10
    hoverEnabled: true
    enabled: tester.running || canStart
    opacity: enabled ? 1 : 0.5
    text: !microphone ? (tester.running ? qsTr("Stop speaker test") : qsTr("Test speakers")) : tester.phase === "playback" ? qsTr("Playing back…") : tester.phase === "ready" ? qsTr("Release to play back") : tester.phase === "recording" ? qsTr("Recording… release to play back") : tester.running ? qsTr("Starting…") : qsTr("Hold to test microphone")
    Accessible.name: text
    onPressed: {
        if (!microphone)
            return;

        cancelOnClick = tester.running;
        if (!cancelOnClick) {
            held = true;
            tester.start("microphone");
        }
    }
    onReleased: {
        if (held) {
            held = false;
            tester.release();
        }
    }
    onCanceled: {
        if (held) {
            held = false;
            tester.cancel();
        }
    }
    onClicked: {
        if (microphone) {
            if (cancelOnClick)
                tester.cancel();
        } else if (tester.running) {
            tester.cancel();
        } else {
            tester.start("speakers");
        }
    }

    PassiveToolTip {
        target: root
        text: root.tester.error || (root.microphone ? qsTr("Hold to record the default microphone; release to hear it through the default output. Unmute both to test. Recordings are limited to 10 seconds.") : qsTr("Test every connected, unmuted output, one speaker channel at a time."))
    }

    contentItem: Item {
        Item {
            id: group

            anchors.centerIn: parent
            width: Math.min(parent.width, 34 + Math.max(title.implicitWidth, subtitle.implicitWidth) + (cancelIcon.visible ? 28 : 0))
            height: parent.height

            Icon {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 22
                height: 22
                visible: !root.tester.running || root.recording
                name: root.microphone ? "mic" : "speaker"
                color: root.recording || root.hovered || root.visualFocus ? Theme.accent : Theme.text
            }

            BusySpinner {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 22
                height: 22
                visible: root.tester.running && !root.recording
            }

            Item {
                x: 34
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, group.width - 34 - (cancelIcon.visible ? 28 : 0))
                height: title.implicitHeight + (subtitle.visible ? subtitle.implicitHeight + 4 : 0)

                ShellText {
                    id: title

                    width: parent.width
                    text: root.text
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    font.weight: Font.Medium
                }

                ShellText {
                    id: subtitle

                    objectName: root.objectName + ":detail"
                    anchors.top: title.bottom
                    anchors.topMargin: 4
                    width: parent.width
                    visible: root.detail !== ""
                    text: root.detail
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    font.pixelSize: Theme.smallFontSize
                    color: root.tester.error ? Theme.danger : Theme.muted
                }
            }

            Icon {
                id: cancelIcon

                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: 16
                height: 16
                name: "x"
                color: Theme.muted
                visible: root.tester.running && !root.held
            }
        }
    }

    background: ButtonBackground {
        idleColor: Theme.surface
        highlighted: root.hovered || root.visualFocus
        pressed: root.down
    }
}
