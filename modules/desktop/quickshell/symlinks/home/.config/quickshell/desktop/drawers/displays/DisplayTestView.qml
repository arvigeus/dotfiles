import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

Item {
    id: root
    objectName: "displayTestView"
    property string mode: "identify"
    property var record: ({
            name: "",
            label: "",
            mode: ""
        })
    property int number: 1
    property int pattern: 0
    property bool controlsVisible: true
    property real distance: 0
    readonly property var patternNames: [qsTr("Black"), qsTr("White"), qsTr("Red"), qsTr("Green"), qsTr("Blue"), qsTr("Grayscale gradient"), qsTr("Checkerboard")]
    readonly property var colors: ["#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff"]
    readonly property bool identifying: mode === "identify"
    signal closeRequested
    function advance(direction: int): void {
        if (mode === "patterns")
            pattern = (pattern + direction + patternNames.length) % patternNames.length;
    }
    onModeChanged: {
        pattern = 0;
        distance = 0;
        controlsVisible = true;
    }
    component TestButton: Button {
        id: button
        implicitHeight: Theme.controlHeight
        padding: 8
        leftPadding: 12
        rightPadding: 12
        hoverEnabled: true
        contentItem: ShellText {
            text: button.text
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: ButtonBackground {
            idleColor: Theme.surface
            highlighted: button.hovered || button.visualFocus
            pressed: button.down
        }
    }
    Rectangle {
        objectName: "displayPatternColor"
        anchors.fill: parent
        visible: root.mode === "patterns" && root.pattern < 5
        color: root.colors[root.pattern] ?? "black"
    }
    Rectangle {
        objectName: "displayPatternGradient"
        anchors.fill: parent
        visible: root.mode === "patterns" && root.pattern === 5
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop {
                position: 0
                color: "black"
            }
            GradientStop {
                position: 1
                color: "white"
            }
        }
    }
    Canvas {
        id: checkerboard
        objectName: "displayPatternCheckerboard"
        anchors.fill: parent
        visible: root.mode === "patterns" && root.pattern === 6
        onVisibleChanged: if (visible)
            requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const context = getContext("2d");
            for (let y = 0; y < height; y += 24) {
                for (let x = 0; x < width; x += 24) {
                    context.fillStyle = ((x / 24 + y / 24) % 2) ? "white" : "black";
                    context.fillRect(x, y, 24, 24);
                }
            }
        }
    }
    Column {
        anchors.fill: parent
        visible: root.mode === "motion"
        Repeater {
            model: ["#141414", "#808080", "#eeeeee"]
            Rectangle {
                id: track
                required property string modelData
                required property int index
                width: root.width
                height: root.height / 3
                color: modelData
                clip: true
                Rectangle {
                    objectName: "displayMotionTarget:" + track.index
                    x: root.distance - width
                    anchors.verticalCenter: parent.verticalCenter
                    width: 100
                    height: Math.min(100, parent.height * 0.6)
                    color: track.index === 2 ? "black" : "white"
                    Rectangle {
                        anchors.centerIn: parent
                        width: 4
                        height: parent.height
                        color: track.index === 2 ? "white" : "black"
                    }
                }
            }
        }
    }
    FrameAnimation {
        running: root.visible && root.mode === "motion"
        onTriggered: root.distance = (root.distance + 600 * frameTime) % (root.width + 100)
    }
    MouseArea {
        objectName: "displayTestDismiss"
        anchors.fill: parent
        enabled: !root.identifying
        onClicked: root.closeRequested()
    }
    Rectangle {
        objectName: "displayIdentityLabel"
        anchors.centerIn: parent
        width: Math.min(440, Math.max(0, root.width - 32))
        height: identity.implicitHeight + 32
        visible: root.identifying
        color: Theme.background
        border.width: 2
        border.color: Theme.accent
        radius: Theme.controlRadius
        ColumnLayout {
            id: identity
            x: 16
            y: 16
            width: parent.width - 32
            spacing: 8
            ShellText {
                text: String(root.number)
                font.pixelSize: 48
                font.weight: Font.DemiBold
                color: Theme.accent
                Layout.alignment: Qt.AlignHCenter
            }
            ShellText {
                text: root.record.name
                font.pixelSize: Theme.titleFontSize
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                textFormat: Text.PlainText
            }
            ShellText {
                text: root.record.label
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
            }
        }
    }
    Rectangle {
        id: controls
        objectName: "displayTestControls"
        anchors.horizontalCenter: parent.horizontalCenter
        y: Math.max(8, root.height - height - 20)
        width: Math.min(600, Math.max(0, root.width - 32))
        height: instructions.implicitHeight + 24
        visible: !root.identifying && root.controlsVisible
        color: Theme.background
        border.width: 1
        border.color: Theme.border
        radius: Theme.controlRadius
        ColumnLayout {
            id: instructions
            x: 12
            y: 12
            width: parent.width - 24
            spacing: 8
            ShellText {
                objectName: "displayTestTitle"
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
                text: root.record.name + " · " + (root.mode === "patterns" ? root.patternNames[root.pattern] : qsTr("Motion test"))
                font.weight: Font.DemiBold
            }
            ShellText {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
                text: root.mode === "patterns" ? qsTr("Space / ← / →: change pattern · H: hide controls · Click or Esc: close") : qsTr("%1 configured · H: hide controls · Click or Esc: close").arg(root.record.mode.split("@")[1] ?? "")
                font.pixelSize: Theme.smallFontSize
                color: Theme.muted
            }
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 8
                TestButton {
                    visible: root.mode === "patterns"
                    text: qsTr("Next pattern")
                    onClicked: root.advance(1)
                }
                TestButton {
                    text: qsTr("Close")
                    onClicked: root.closeRequested()
                }
            }
        }
    }
}
