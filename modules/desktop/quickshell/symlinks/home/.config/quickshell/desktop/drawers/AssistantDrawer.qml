pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window
import "../ui"
import "assistant"
import "assistant/Markdown.js" as Markdown

DrawerPage {
    id: root
    readonly property alias optionsPopup: options
    readonly property alias modelPopup: modelPicker
    readonly property alias attachmentDialog: fileChooser
    readonly property alias attachmentPreview: filePreview
    initialFocus: composer
    readonly property var lengths: [
        {
            id: "brief",
            label: qsTr("Brief")
        },
        {
            id: "balanced",
            label: qsTr("Balanced")
        },
        {
            id: "detailed",
            label: qsTr("Detailed")
        }
    ]
    escapeHandler: options.visible || modelPicker.visible || fileChooser.visible || filePreview.visible ? () => {
        if (fileChooser.visible)
            fileChooser.reject();
        else if (filePreview.visible)
            filePreview.close();
        else {
            options.close();
            modelPicker.close();
        }
        return true;
    } : null

    onActiveChanged: {
        AssistantService.observed = active;
        if (!active) {
            options.close();
            modelPicker.close();
            fileChooser.close();
            filePreview.close();
        }
    }
    Component.onDestruction: {
        AssistantService.observed = false;
        fileChooser.close();
    }
    Connections {
        target: AssistantService
        function onAppOpened(): void {
            root.closeRequested();
        }
        function onPasted(cursor: int): void {
            Qt.callLater(() => {
                if (root.active && !fileChooser.visible && !filePreview.visible) {
                    composer.cursorPosition = cursor;
                    composer.forceActiveFocus();
                }
            });
        }
    }

    function submit(): void {
        if (AssistantService.send()) {
            conversation.followTail = true;
            composer.forceActiveFocus();
        }
    }

    headerActions: RowLayout {
        spacing: 4
        IconButton {
            objectName: "assistantNew"
            iconName: "plus"
            text: qsTr("New chat")
            hint: qsTr("New chat · discard this conversation")
            enabled: !AssistantService.busy && (AssistantService.messages.count > 0 || !!AssistantService.draft || AssistantService.attachments.length > 0)
            onClicked: {
                AssistantService.newChat();
                composer.forceActiveFocus();
            }
        }
        IconButton {
            objectName: "assistantEdit"
            iconName: "pencil"
            text: qsTr("Open Lemonade")
            hint: qsTr("Open the full Lemonade app · starts the server if needed")
            enabled: AssistantService.installed && (AssistantService.online || !AssistantService.busy)
            onClicked: AssistantService.openApp()
        }
        IconButton {
            objectName: "assistantServer"
            iconName: "power"
            iconColor: AssistantService.online ? Theme.success : Theme.muted
            text: AssistantService.online || AssistantService.serverState === "active" ? qsTr("Stop Lemonade") : qsTr("Start Lemonade")
            hint: AssistantService.downloading || AssistantService.serverInUse ? qsTr("Lemonade is downloading or serving a request") : text + (AssistantService.scope === "system" ? "\n" + qsTr("System service · authentication may be required") : "")
            enabled: AssistantService.checked && AssistantService.installed && !AssistantService.busy && !AssistantService.downloading && !AssistantService.serverInUse
            onClicked: AssistantService.setServer(!(AssistantService.online || AssistantService.serverState === "active"))
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingMedium

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMedium
            ShellButton {
                id: modelChoice
                objectName: "assistantModel"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: AssistantService.selectedEntry?.label || AssistantService.selectedModel || qsTr("Choose a model")
                iconName: AssistantService.selectedLoaded ? "circle-dot" : "chevron-down"
                enabled: AssistantService.installed && !AssistantService.working && !AssistantService.preparing
                Accessible.name: qsTr("Local chat model")
                onClicked: {
                    options.close();
                    modelPicker.visible ? modelPicker.close() : modelPicker.open();
                }
                PassiveToolTip {
                    target: modelChoice
                    text: AssistantService.selectedLoaded ? qsTr("%1 · loaded in Lemonade").arg(AssistantService.selectedModel) : qsTr("Choose or download a local chat model · starts Lemonade if needed")
                }
            }
            IconButton {
                id: optionsButton
                objectName: "assistantOptions"
                iconName: "sliders-horizontal"
                text: qsTr("Assistant options")
                hint: qsTr("Thinking, reply length, style and model memory")
                onClicked: {
                    modelPicker.close();
                    options.visible ? options.close() : options.open();
                }
            }
        }

        ShellText {
            objectName: "assistantStatus"
            Layout.fillWidth: true
            visible: !AssistantService.checked || AssistantService.changingServer || !AssistantService.online || !!AssistantService.selectedDownload || (!!AssistantService.selectedEntry && !AssistantService.modelAvailable)
            text: !AssistantService.checked ? qsTr("Checking Lemonade…") : AssistantService.changingServer ? (AssistantService.pendingOperation === "stop" ? qsTr("Stopping Lemonade…") : qsTr("Starting Lemonade…")) : !AssistantService.online ? qsTr("Lemonade is stopped · starts when needed") : AssistantService.selectedDownload?.running ? (modelPicker.progress(AssistantService.selectedDownload) >= 0 ? qsTr("Downloading %1 · %2%").arg(AssistantService.selectedModel).arg(Math.floor(modelPicker.progress(AssistantService.selectedDownload) * 100)) : qsTr("Downloading %1…").arg(AssistantService.selectedModel)) : AssistantService.selectedDownload?.status === "paused" ? qsTr("Model download paused") : AssistantService.selectedDownload?.error || (!AssistantService.modelAvailable && AssistantService.selectedEntry ? AssistantService.generating ? qsTr("Downloading %1…").arg(AssistantService.selectedModel) : qsTr("%1 will download on first message").arg(AssistantService.selectedModel) : "")
            color: Theme.muted
            elide: Text.ElideRight
            font.pixelSize: Theme.smallFontSize
        }

        ShellText {
            objectName: "assistantError"
            Layout.fillWidth: true
            visible: !!text
            text: [AssistantService.error, AssistantService.saveError, AssistantService.attachmentError, AssistantService.attachmentHint].filter(Boolean).join("\n")
            color: Theme.danger
            wrapMode: Text.Wrap
            font.pixelSize: Theme.smallFontSize
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 50

            ScrollListView {
                id: conversation
                objectName: "assistantConversation"
                anchors.fill: parent
                spacing: Theme.gap
                model: AssistantService.messages
                property bool followTail: true
                property bool positioning: false
                function showLatest(): void {
                    if (!followTail)
                        return;
                    positioning = true;
                    positionViewAtEnd();
                    positioning = false;
                }
                onContentYChanged: if (!positioning)
                    followTail = atYEnd
                onContentHeightChanged: Qt.callLater(showLatest)
                onHeightChanged: Qt.callLater(showLatest)
                ScrollBar.vertical: ScrollBar {}
                delegate: Item {
                    id: message
                    required property int index
                    required property string speaker
                    required property string body
                    required property string modelName
                    required property string state
                    required property string filesJson
                    required property string reasoning
                    property bool thoughtsExpanded: false
                    readonly property bool assistant: speaker === "assistant"
                    width: conversation.width
                    implicitHeight: bubble.implicitHeight
                    Card {
                        id: bubble
                        x: message.assistant ? 0 : Theme.paddingLarge
                        width: parent.width - (message.assistant ? 0 : Theme.paddingLarge)
                        implicitHeight: messageContent.implicitHeight + Theme.gap * 2
                        color: message.assistant ? Theme.surface : Theme.accentSurface
                        ColumnLayout {
                            id: messageContent
                            anchors.fill: parent
                            anchors.margins: Theme.gap
                            spacing: Theme.spacingSmall
                            RowLayout {
                                Layout.fillWidth: true
                                ShellText {
                                    Layout.fillWidth: true
                                    text: message.assistant ? message.modelName : qsTr("You")
                                    font.pixelSize: Theme.smallFontSize
                                    color: Theme.muted
                                    elide: Text.ElideRight
                                }
                                IconButton {
                                    objectName: "assistantEditMessage:" + message.index
                                    visible: !message.assistant && message.index === AssistantService.lastUserIndex
                                    enabled: AssistantService.canEditLast
                                    implicitWidth: 26
                                    implicitHeight: 26
                                    padding: 5
                                    iconName: "pencil"
                                    text: qsTr("Edit message")
                                    hint: AssistantService.draft.trim() || AssistantService.attachments.length ? qsTr("Send or clear the current draft before editing this message") : qsTr("Edit this message and its attachments")
                                    onClicked: {
                                        if (AssistantService.editLast())
                                            composer.forceActiveFocus();
                                    }
                                }
                                IconButton {
                                    objectName: "assistantCopy:" + message.index
                                    implicitWidth: 26
                                    implicitHeight: 26
                                    padding: 5
                                    iconName: copied.running ? "check" : "copy"
                                    text: copied.running ? qsTr("Copied") : qsTr("Copy message")
                                    enabled: !!message.body
                                    onClicked: {
                                        // Use the native text selection clipboard path, never argv.
                                        answer.selectAll();
                                        answer.copy();
                                        answer.deselect();
                                        copied.restart();
                                    }
                                    Timer {
                                        id: copied
                                        interval: 1500
                                    }
                                }
                                IconButton {
                                    objectName: "assistantRetry:" + message.index
                                    visible: message.assistant && message.index === AssistantService.messages.count - 1 && !AssistantService.generating
                                    enabled: AssistantService.installed && !!AssistantService.selectedModel && !AssistantService.busy
                                    implicitWidth: 26
                                    implicitHeight: 26
                                    padding: 5
                                    iconName: "rotate-ccw"
                                    text: qsTr("Retry reply")
                                    onClicked: AssistantService.retry()
                                }
                            }
                            AttachmentStrip {
                                Layout.fillWidth: true
                                visible: files.length > 0
                                files: JSON.parse(message.filesJson || "[]")
                                onPreviewRequested: file => {
                                    filePreview.file = file;
                                    filePreview.open();
                                }
                            }
                            ShellButton {
                                Layout.fillWidth: true
                                visible: !!message.reasoning
                                text: message.thoughtsExpanded ? qsTr("Hide thinking") : qsTr("Show thinking")
                                iconName: message.thoughtsExpanded ? "chevron-up" : "chevron-down"
                                onClicked: message.thoughtsExpanded = !message.thoughtsExpanded
                            }
                            ScrollView {
                                Layout.fillWidth: true
                                Layout.preferredHeight: Math.min(160, thoughts.contentHeight + 12)
                                visible: message.thoughtsExpanded && !!message.reasoning
                                contentWidth: availableWidth
                                clip: true
                                TextArea {
                                    id: thoughts
                                    text: message.reasoning
                                    readOnly: true
                                    selectByMouse: true
                                    color: Theme.muted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.smallFontSize
                                    wrapMode: TextEdit.Wrap
                                    textFormat: TextEdit.PlainText
                                    background: null
                                }
                            }
                            TextArea {
                                id: answer
                                objectName: "assistantMessage:" + message.index
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                padding: 0
                                readOnly: true
                                selectByMouse: true
                                activeFocusOnTab: true
                                color: Theme.text
                                selectionColor: Theme.accent
                                selectedTextColor: Theme.accentText
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize
                                wrapMode: TextEdit.Wrap
                                text: Markdown.prepare(message.body)
                                textFormat: TextEdit.MarkdownText
                                visible: !!message.body
                                background: null
                                onLinkActivated: link => {
                                    if (/^https?:\/\//i.test(link))
                                        Apps.launch(["xdg-open", link]);
                                }
                            }
                            RowLayout {
                                visible: message.state === "streaming" || message.state === "stopped" || message.state === "limited"
                                spacing: Theme.spacingMedium
                                BusySpinner {
                                    Layout.preferredWidth: 14
                                    Layout.preferredHeight: 14
                                    visible: message.state === "streaming"
                                    running: root.active && visible
                                }
                                ShellText {
                                    text: message.state === "stopped" ? qsTr("Stopped") : message.state === "limited" ? qsTr("Output limit reached") : AssistantService.cancelling ? qsTr("Stopping…") : !AssistantService.modelAvailable ? qsTr("Downloading model…") : message.body ? qsTr("Answering…") : AssistantService.thinking ? qsTr("Thinking…") : qsTr("Preparing reply…")
                                    color: Theme.muted
                                    font.pixelSize: Theme.smallFontSize
                                }
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                anchors.centerIn: parent
                width: Math.max(0, parent.width - Theme.paddingLarge * 2)
                visible: AssistantService.messages.count === 0
                spacing: Theme.gap
                Icon {
                    name: "bot"
                    color: Theme.muted
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 40
                    Layout.alignment: Qt.AlignHCenter
                }
                ShellText {
                    Layout.fillWidth: true
                    text: !AssistantService.installed ? qsTr("Lemonade is not installed") : AssistantService.checked && AssistantService.online && !AssistantService.selectedEntry ? qsTr("Choose a model to get started") : qsTr("What’s on your mind?")
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: Theme.muted
                }
            }

            IconButton {
                objectName: "assistantLatest"
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: Theme.spacingMedium
                visible: AssistantService.messages.count > 0 && !conversation.atYEnd
                iconName: "arrow-down"
                text: qsTr("Latest reply")
                onClicked: {
                    conversation.followTail = true;
                    conversation.showLatest();
                }
            }
        }

        AttachmentStrip {
            objectName: "assistantDraftAttachments"
            Layout.fillWidth: true
            visible: files.length > 0
            maximumHeight: Math.min(120, root.height * 0.2)
            files: AssistantService.attachments
            removable: true
            onRemoved: id => AssistantService.removeAttachment(id)
            onPreviewRequested: file => {
                filePreview.file = file;
                filePreview.open();
            }
        }
        ShellText {
            Layout.fillWidth: true
            visible: AssistantService.preparing
            text: qsTr("Preparing attachments…")
            color: Theme.muted
            font.pixelSize: Theme.smallFontSize
        }

        Card {
            objectName: "assistantInput"
            Layout.fillWidth: true
            implicitHeight: composerLayout.implicitHeight + Theme.spacingMedium * 2
            border.color: composer.activeFocus ? Theme.accent : Theme.border
            ColumnLayout {
                id: composerLayout
                anchors.fill: parent
                anchors.margins: Theme.spacingMedium
                spacing: Theme.spacingSmall
                ScrollView {
                    objectName: "assistantEditor"
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(120, Math.max(42, composer.contentHeight + composer.topPadding + composer.bottomPadding))
                    contentWidth: availableWidth
                    clip: true
                    TextArea {
                        id: composer
                        objectName: "assistantComposer"
                        text: AssistantService.draft
                        onTextChanged: AssistantService.draft = text
                        enabled: AssistantService.installed
                        placeholderText: qsTr("Ask anything…")
                        placeholderTextColor: Theme.muted
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize
                        selectByMouse: true
                        wrapMode: TextEdit.Wrap
                        textFormat: TextEdit.PlainText
                        padding: Theme.spacingSmall
                        selectionColor: Theme.accent
                        selectedTextColor: Theme.accentText
                        background: null
                        Accessible.name: qsTr("Message")
                        Keys.onPressed: event => {
                            if (event.key === Qt.Key_V && (event.modifiers & Qt.ControlModifier) && !(event.modifiers & Qt.ShiftModifier)) {
                                AssistantService.paste(selectionStart, selectionEnd);
                                event.accepted = true;
                                return;
                            }
                            if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !(event.modifiers & Qt.ShiftModifier) && !(event.modifiers & Qt.ControlModifier) && !inputMethodComposing) {
                                root.submit();
                                event.accepted = true;
                            }
                        }
                        PassiveToolTip {
                            target: composer
                            text: qsTr("Enter to send · Shift+Enter for a new line\nCtrl+V pastes text, images or files")
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall
                    IconButton {
                        objectName: "assistantAttach"
                        implicitWidth: 32
                        implicitHeight: 32
                        padding: 7
                        iconName: "paperclip"
                        text: qsTr("Attach files")
                        hint: qsTr("Attach images, documents or text/code files\nDrop files here, or paste with Ctrl+V")
                        enabled: !AssistantService.preparing
                        onClicked: fileChooser.open()
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    IconButton {
                        id: sendButton
                        objectName: "assistantSend"
                        implicitWidth: 32
                        implicitHeight: 32
                        padding: 7
                        iconName: AssistantService.generating ? "square" : "arrow-up"
                        iconColor: AssistantService.generating ? Theme.danger : enabled ? Theme.accentText : Theme.muted
                        text: AssistantService.generating ? qsTr("Stop reply") : qsTr("Send message")
                        hint: AssistantService.generating ? text : (!AssistantService.online ? qsTr("Start Lemonade and send message · Enter") : !AssistantService.modelAvailable && AssistantService.selectedEntry ? qsTr("Download %1 and send message · Enter").arg(AssistantService.selectedModel) : qsTr("Send message · Enter")) + "\n" + qsTr("Shift+Enter for a new line")
                        enabled: AssistantService.generating ? !AssistantService.cancelling : AssistantService.canSend
                        contentItem: Icon {
                            name: sendButton.iconName
                            color: sendButton.iconColor
                        }
                        background: Rectangle {
                            radius: Theme.controlRadius
                            color: sendButton.enabled && !AssistantService.generating ? (sendButton.down ? Theme.accentSurface : Theme.accent) : (sendButton.hovered ? Theme.surface : "transparent")
                            border.color: sendButton.visualFocus ? Theme.accent : "transparent"
                        }
                        onClicked: AssistantService.generating ? AssistantService.cancel() : root.submit()
                    }
                }
            }
        }
        ShellText {
            Layout.fillWidth: true
            visible: AssistantService.messages.count >= 80
            text: qsTr("Start a new chat to continue.")
            color: Theme.muted
            font.pixelSize: Theme.smallFontSize
        }
    }

    InfoPopover {
        id: options
        objectName: "assistantOptionsPopup"
        button: optionsButton
        active: root.active
        ShellText {
            text: qsTr("Reply length")
            font.weight: Font.Medium
        }
        ShellChoice {
            id: lengthChoice
            objectName: "assistantLength"
            Layout.fillWidth: true
            model: root.lengths
            textRole: "label"
            currentIndex: root.lengths.findIndex(row => row.id === AssistantService.responseLength)
            enabled: !AssistantService.busy
            Accessible.name: qsTr("Reply length")
            onActivated: index => AssistantService.chooseLength(root.lengths[index].id)
            PassiveToolTip {
                target: lengthChoice
                text: qsTr("How concise the final answer should be · output limits follow Lemonade")
            }
        }
        ShellText {
            text: qsTr("Thinking")
            font.weight: Font.Medium
            visible: !!AssistantService.selectedEntry
        }
        ShellChoice {
            id: thinkingChoice
            objectName: "assistantThinking"
            Layout.fillWidth: true
            visible: !!AssistantService.selectedEntry
            model: [qsTr("Model default"), qsTr("On"), qsTr("Off")]
            currentIndex: ["auto", "on", "off"].indexOf(AssistantService.thinkingMode)
            enabled: !AssistantService.busy
            Accessible.name: qsTr("Thinking")
            onActivated: index => AssistantService.chooseThinking(["auto", "on", "off"][index])
            PassiveToolTip {
                target: thinkingChoice
                text: qsTr("Off requests a direct answer · remembered for this model\nUses Lemonade’s thinking control; support depends on the model")
            }
        }
        ShellText {
            text: qsTr("Response style")
            font.weight: Font.Medium
        }
        ShellChoice {
            id: styleChoice
            objectName: "assistantStyle"
            Layout.fillWidth: true
            model: [qsTr("Model default"), qsTr("Precise"), qsTr("Creative")]
            currentIndex: ["default", "precise", "creative"].indexOf(AssistantService.responseStyle)
            enabled: !AssistantService.busy
            Accessible.name: qsTr("Response style")
            onActivated: index => AssistantService.chooseStyle(["default", "precise", "creative"][index])
            PassiveToolTip {
                target: styleChoice
                text: qsTr("Keep model defaults, or favor consistency or variety")
            }
        }
        ShellButton {
            id: releaseButton
            objectName: "assistantRelease"
            Layout.fillWidth: true
            text: qsTr("Release model memory")
            iconName: "memory-stick"
            enabled: AssistantService.online && AssistantService.canRelease
            onClicked: AssistantService.releaseModel()
            PassiveToolTip {
                target: releaseButton
                text: qsTr("Unload the selected idle model; keep it installed")
            }
        }
    }
    ModelPicker {
        id: modelPicker
        objectName: "assistantModelPopup"
        button: modelChoice
        active: root.active
        maximumWidth: root.width
    }
    FileDialog {
        id: fileChooser
        title: qsTr("Attach images or documents")
        parentWindow: root.Window.window
        options: FileDialog.DontUseNativeDialog
        popupType: Popup.Item
        fileMode: FileDialog.OpenFiles
        nameFilters: [qsTr("Images and documents (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff *.avif *.heic *.pdf *.docx *.odt *.txt *.md *.csv *.json *.xml *.yaml *.yml *.log)"), qsTr("All files (*)")]
        onAccepted: if (root.active) {
            AssistantService.attachUrls(selectedFiles);
            composer.forceActiveFocus();
        }
        onRejected: if (root.active)
            composer.forceActiveFocus()
    }
    Popup {
        id: filePreview
        property var file: null
        parent: root
        popupType: Popup.Item
        width: root.width
        height: Math.min(root.height, 560)
        y: Math.max(0, (root.height - height) / 2)
        padding: Theme.gap
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: file = null
        background: Surface {
            color: Theme.background
            radius: Theme.controlRadius
        }
        contentItem: ColumnLayout {
            RowLayout {
                Layout.fillWidth: true
                ShellText {
                    Layout.fillWidth: true
                    text: filePreview.file?.name || ""
                    elide: Text.ElideMiddle
                }
                IconButton {
                    iconName: "x"
                    text: qsTr("Close preview")
                    onClicked: filePreview.close()
                }
            }
            Image {
                objectName: "assistantImagePreview"
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: filePreview.file?.kind === "image"
                source: visible ? filePreview.file.data : ""
                cache: false
                fillMode: Image.PreserveAspectFit
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: filePreview.file?.kind === "text"
                contentWidth: availableWidth
                clip: true
                TextArea {
                    text: filePreview.file?.text || ""
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    textFormat: TextEdit.PlainText
                    color: Theme.text
                    font.family: Theme.monospaceFamily
                    font.pixelSize: Theme.smallFontSize
                    background: null
                }
            }
        }
    }
    DropArea {
        id: fileDrop
        objectName: "assistantFileDrop"
        anchors.fill: parent
        enabled: root.active
        onEntered: drag => {
            drag.accepted = drag.hasUrls && drag.urls.every(url => String(url).startsWith("file:"));
        }
        onDropped: drop => {
            AssistantService.attachUrls(drop.urls);
            drop.acceptProposedAction();
        }
    }
    Rectangle {
        anchors.fill: parent
        visible: fileDrop.containsDrag
        color: Theme.accentSurface
        border.color: Theme.accent
        radius: Theme.controlRadius
        ShellText {
            anchors.centerIn: parent
            text: qsTr("Drop to attach")
            font.weight: Font.Medium
        }
    }
}
