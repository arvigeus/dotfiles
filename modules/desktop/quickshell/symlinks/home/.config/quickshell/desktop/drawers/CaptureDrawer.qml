pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import Quickshell
import "../ui"
import "capture"

DrawerPage {
    id: root
    property var service: CaptureService
    property var webcams: visibleWebcams(devices.videoInputs)
    property var openCamera: null
    property var outputs: Quickshell.screens
    readonly property string selectedOutput: outputs.some(output => output.name === service.output) ? service.output : screen?.name ?? outputs[0]?.name ?? ""
    readonly property alias screenshotMenu: timing
    readonly property alias recordingMenu: recordingOptions
    escapeHandler: timing.visible || recordingOptions.visible || !!openCamera?.settingsOpen ? () => {
        closePopovers();
        return true;
    } : null
    onActiveChanged: if (!active)
        closePopovers()
    function visibleWebcams(inputs): var {
        const regular = inputs.filter(device => !/\bIR\b|infrared/i.test(device.description));
        // Laptop infrared companion sensors are not ordinary video-call cameras.
        return regular.length ? regular : inputs;
    }
    function closePopovers(): void {
        timing.close();
        recordingOptions.close();
        openCamera?.closeSettings();
        openCamera = null;
    }
    function takeScreenshot(seconds: int, mode = "output"): void {
        closePopovers();
        service.delay = seconds;
        if (service.capture(selectedOutput, mode))
            closeRequested();
    }
    MediaDevices {
        id: devices
    }
    component Heading: ShellText {
        Layout.fillWidth: true
        font.weight: Font.DemiBold
    }
    component Note: ShellText {
        Layout.fillWidth: true
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
    component MenuEntry: MenuItem {
        id: entry
        property string iconName: ""
        property string hint: ""
        Layout.fillWidth: true
        implicitWidth: label.implicitWidth + leftPadding + rightPadding + 24
        implicitHeight: Math.max(32, label.implicitHeight + 12)
        highlighted: hovered || visualFocus
        padding: 6
        spacing: 8
        hoverEnabled: true
        opacity: enabled ? 1 : 0.45
        indicator: Item {}
        contentItem: Item {
            implicitWidth: label.implicitWidth + 24
            implicitHeight: label.implicitHeight
            Icon {
                objectName: entry.objectName + "Icon"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 16
                height: 16
                name: entry.checkable ? "check" : entry.iconName
                opacity: entry.checkable && !entry.checked ? 0 : 1
                color: entry.highlighted ? Theme.accent : Theme.text
            }
            ShellText {
                id: label
                objectName: entry.objectName + "Label"
                anchors.left: parent.left
                anchors.leftMargin: 24
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: entry.text
                wrapMode: Text.NoWrap
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignLeft
            }
        }
        background: ButtonBackground {
            objectName: entry.objectName + "Background"
            highlighted: entry.highlighted
            pressed: entry.down
        }
        PassiveToolTip {
            target: entry
            text: entry.hint
        }
    }
    component RecordingOption: MenuEntry {
        id: option
        required property string optionKey
        checkable: true
        checked: !!root.service.recorder.options?.[optionKey]
        enabled: root.active && root.service.recorder.available && !!root.service.recorder.options && !root.service.sessionActive && !root.service.savingRecordingOption && !root.service.recordingPending
        onToggled: {
            const requested = checked;
            checked = Qt.binding(() => !!root.service.recorder.options?.[optionKey]);
            root.service.setRecordingOption(optionKey, requested);
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            visible: root.service.error !== ""
            Note {
                objectName: "captureError"
                text: root.service.error
                color: Theme.danger
            }
            IconButton {
                iconName: "x"
                text: qsTr("Dismiss capture error")
                onClicked: root.service.dismissError()
            }
        }
        DrawerColumn {
            id: captureScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                CaptureButton {
                    id: screenshotButton
                    objectName: "captureScreenshot"
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    text: qsTr("Screenshot")
                    iconName: "camera"
                    hint: qsTr("Capture the full display now")
                    actionEnabled: root.active && !root.service.waiting && !root.service.capturing && !!root.selectedOutput
                    optionsEnabled: root.active && !root.service.waiting && !root.service.capturing
                    onClicked: root.takeScreenshot(0)
                    onOptionsClicked: {
                        if (timing.visible)
                            timing.close();
                        else {
                            root.closePopovers();
                            timing.open();
                        }
                    }
                    InfoPopover {
                        id: timing
                        objectName: "captureTimingPopup"
                        button: screenshotButton.menuButton
                        active: root.active
                        width: Math.min(contentItem.naturalContentWidth + leftPadding + rightPadding + 12, Math.max(0, (Overlay.overlay?.width ?? 416) - 16))
                        padding: 6
                        contentSpacing: 2
                        Repeater {
                            model: [
                                {
                                    seconds: 3,
                                    mode: "output"
                                },
                                {
                                    seconds: 3,
                                    mode: "region"
                                },
                                {
                                    seconds: 5,
                                    mode: "output"
                                },
                                {
                                    seconds: 5,
                                    mode: "region"
                                },
                                {
                                    seconds: 10,
                                    mode: "output"
                                },
                                {
                                    seconds: 10,
                                    mode: "region"
                                }
                            ]
                            MenuEntry {
                                required property var modelData
                                objectName: "captureDelay:" + modelData.seconds + ":" + modelData.mode
                                iconName: "alarm-clock"
                                enabled: modelData.mode === "region" || !!root.selectedOutput
                                text: modelData.mode === "region" ? qsTr("After %1 seconds (region)").arg(modelData.seconds) : qsTr("After %1 seconds (fullscreen)").arg(modelData.seconds)
                                onClicked: root.takeScreenshot(modelData.seconds, modelData.mode)
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 1
                            Layout.topMargin: 4
                            Layout.bottomMargin: 4
                            color: Theme.border
                        }
                        MenuEntry {
                            objectName: "captureEdit"
                            text: qsTr("Open in editor")
                            checkable: true
                            checked: root.service.edit
                            enabled: root.service.save
                            onToggled: {
                                const value = checked;
                                checked = Qt.binding(() => root.service.edit);
                                root.service.setEdit(value);
                            }
                        }
                        MenuEntry {
                            objectName: "captureSave"
                            text: qsTr("Save to disk")
                            checkable: true
                            checked: root.service.save
                            onToggled: {
                                const value = checked;
                                checked = Qt.binding(() => root.service.save);
                                root.service.setSave(value);
                            }
                        }
                        ShellChoice {
                            objectName: "captureDisplay"
                            Layout.fillWidth: true
                            visible: root.outputs.length > 1
                            Accessible.name: qsTr("Display to capture")
                            model: root.outputs.map(output => output.name)
                            currentIndex: root.outputs.findIndex(output => output.name === root.selectedOutput)
                            onActivated: index => root.service.output = root.outputs[index].name
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 1
                            Layout.topMargin: 4
                            Layout.bottomMargin: 4
                            color: Theme.border
                        }
                        MenuEntry {
                            objectName: "captureFolder"
                            iconName: "folder-open"
                            text: qsTr("Open screenshots folder")
                            enabled: !!root.service.recorder.pictures
                            hint: root.service.recorder.pictures
                            onClicked: {
                                root.closePopovers();
                                root.service.openFolder("pictures");
                            }
                        }
                        MenuEntry {
                            objectName: "captureLastImage"
                            iconName: "eye"
                            text: qsTr("Open last saved screenshot")
                            visible: !!root.service.lastImage
                            onClicked: {
                                root.closePopovers();
                                root.service.openPath(root.service.lastImage);
                            }
                        }
                    }
                }
                CaptureButton {
                    id: recorderButton
                    objectName: "captureRecording"
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    text: root.service.sessionActive ? qsTr("Stop") : qsTr("Recording")
                    iconName: root.service.sessionActive ? "square" : "video"
                    hint: root.service.sessionActive ? qsTr("Stop and save recording") : qsTr("Record the full display")
                    highlighted: root.service.sessionActive
                    actionEnabled: root.active && root.service.recorder.available && !root.service.recordingPending && root.service.recorder.phase !== "stopping"
                    optionsEnabled: root.active && root.service.recorder.available
                    onClicked: {
                        root.closePopovers();
                        if (root.service.record(root.selectedOutput) && !root.service.sessionActive)
                            root.closeRequested();
                    }
                    onOptionsClicked: {
                        if (recordingOptions.visible)
                            recordingOptions.close();
                        else {
                            root.closePopovers();
                            recordingOptions.open();
                        }
                    }
                    InfoPopover {
                        id: recordingOptions
                        objectName: "captureRecordingPopup"
                        button: recorderButton.menuButton
                        active: root.active
                        width: Math.min(contentItem.naturalContentWidth + leftPadding + rightPadding + 12, Math.max(0, (Overlay.overlay?.width ?? 416) - 16))
                        padding: 6
                        contentSpacing: 2
                        RecordingOption {
                            objectName: "recordSystemAudio"
                            optionKey: "systemAudio"
                            text: qsTr("System audio")
                        }
                        RecordingOption {
                            objectName: "recordMicrophone"
                            optionKey: "microphone"
                            text: qsTr("Microphone")
                        }
                        RecordingOption {
                            objectName: "recordPointer"
                            optionKey: "pointer"
                            text: qsTr("Show pointer")
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 1
                            Layout.topMargin: 4
                            Layout.bottomMargin: 4
                            color: Theme.border
                        }
                        MenuEntry {
                            objectName: "recordFolder"
                            iconName: "folder-open"
                            text: qsTr("Open recordings folder")
                            enabled: !!root.service.recorder.videos
                            hint: root.service.recorder.videos
                            onClicked: {
                                root.closePopovers();
                                root.service.openFolder("videos");
                            }
                        }
                        MenuEntry {
                            objectName: "recordLastVideo"
                            iconName: "eye"
                            text: qsTr("Open last recording")
                            visible: !!root.service.recorder.lastVideo
                            onClicked: {
                                root.closePopovers();
                                root.service.openPath(root.service.recorder.lastVideo);
                            }
                        }
                    }
                }
            }
            ShellButton {
                objectName: "captureCancel"
                Layout.fillWidth: true
                visible: root.service.waiting || root.service.capturing
                text: root.service.capturing ? qsTr("Capturing…") : qsTr("Cancel screenshot · %1 s").arg(root.service.remaining)
                iconName: root.service.capturing ? "camera" : "x"
                enabled: root.service.waiting
                onClicked: root.service.cancel()
            }
            RowLayout {
                Layout.fillWidth: true
                visible: root.service.recordingPending || root.service.sessionActive
                Note {
                    objectName: "captureRecordingState"
                    text: root.service.recordingPending || root.service.recorder.phase === "starting" ? qsTr("Starting recording…") : root.service.recorder.phase === "stopping" ? qsTr("Saving recording…") : (root.service.paused ? qsTr("Paused · %1") : qsTr("Recording · %1")).arg(root.service.recordingTime)
                    color: root.service.paused ? Theme.muted : Theme.danger
                }
                IconButton {
                    objectName: "capturePause"
                    visible: ["recording", "paused"].includes(root.service.recorder.phase)
                    iconName: root.service.paused ? "play" : "pause"
                    text: root.service.paused ? qsTr("Resume recording") : qsTr("Pause recording")
                    enabled: !root.service.savingRecordingOption
                    onClicked: root.service.pauseRecording()
                }
            }
            Heading {
                text: qsTr("Webcams")
                Layout.topMargin: 8
            }
            Note {
                objectName: "webcamsEmpty"
                visible: !root.webcams.length
                text: qsTr("No webcams connected.")
            }
            Repeater {
                model: root.webcams
                delegate: WebcamCard {
                    id: cameraCard
                    required property var modelData
                    objectName: "webcam:" + String(modelData.id)
                    device: modelData
                    active: root.active
                    onSettingsRequested: {
                        root.closePopovers();
                        root.openCamera = cameraCard;
                    }
                    onPreviewRequested: Qt.callLater(() => {
                        const view = captureScroll.contentItem;
                        const position = cameraCard.mapToItem(view.contentItem, 0, cameraCard.height).y - view.height;
                        view.contentY = Math.max(0, Math.min(view.contentHeight - view.height, position));
                    })
                }
            }
        }
    }
}
