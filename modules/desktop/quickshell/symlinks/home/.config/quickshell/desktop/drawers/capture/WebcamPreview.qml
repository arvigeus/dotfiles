pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtMultimedia
import "../../ui"

ColumnLayout {
    id: root
    property bool active: false
    required property var device
    property string cameraError: ""
    property bool ready: false
    readonly property bool cameraActive: camera.active
    Layout.fillWidth: true
    spacing: 8

    Camera {
        id: camera
        cameraDevice: root.device
        active: root.active
        onActiveChanged: root.ready = active
        onCameraDeviceChanged: root.cameraError = ""
        onErrorOccurred: (error, message) => root.cameraError = message || qsTr("Could not start the webcam.")
    }
    CaptureSession {
        camera: camera
        videoOutput: video
    }
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: width * 9 / 16
        color: "#111111"
        radius: Theme.controlRadius
        clip: true
        VideoOutput {
            id: video
            objectName: "webcamVideo"
            anchors.fill: parent
            mirrored: true
            fillMode: VideoOutput.PreserveAspectFit
        }
        ShellText {
            anchors.fill: parent
            anchors.margins: 16
            visible: root.cameraError !== "" || !root.ready
            text: root.cameraError ? qsTr("Webcam unavailable\n%1").arg(root.cameraError) : qsTr("Starting webcam…")
            color: "#eeeeee"
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }
    ShellText {
        Layout.fillWidth: true
        text: qsTr("Mirrored preview · no audio or recording")
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap
    }
}
