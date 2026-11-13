pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Effects
import QtQuick.Layouts
import QtQuick.Window
import Quickshell
import Quickshell.Io
import "../ui"
import "assistant"
import "assistant/Markdown.js" as Markdown

DrawerPage {
    id: root
    property string accountAvatar: ""
    property bool componentReady: false
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
    readonly property var promptStarters: [
        {
            label: qsTr("Explain a topic"),
            prompt: qsTr("Explain this topic: ")
        },
        {
            label: qsTr("Debug an error"),
            prompt: qsTr("Help me debug this error:\n")
        },
        {
            label: qsTr("Summarize text"),
            prompt: qsTr("Summarize this text:\n")
        }
    ]
    // Kept outside the status row: an item inside a hidden container reports
    // itself hidden, so the row could never show again.
    readonly property string statusText: {
        const service = AssistantService;
        if (!service.checked)
            return qsTr("Checking Lemonade…");
        if (service.changingServer)
            return service.pendingOperation === "stop" ? qsTr("Stopping Lemonade…") : qsTr("Starting Lemonade…");
        if (!service.online)
            return qsTr("Lemonade is stopped · starts when needed");
        const job = service.selectedDownload;
        if (job?.running) {
            const fraction = modelPicker.progress(job);
            return fraction >= 0 ? qsTr("Downloading %1 · %2%").arg(service.selectedModel).arg(Math.floor(fraction * 100)) : qsTr("Downloading %1…").arg(service.selectedModel);
        }
        if (job?.status === "paused")
            return qsTr("Model download paused");
        if (job?.error)
            return job.error;
        if (service.selectedEntry && !service.modelAvailable)
            return service.generating ? qsTr("Downloading %1…").arg(service.selectedModel) : qsTr("%1 will download on first message").arg(service.selectedModel);
        return "";
    }
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
        if (active && componentReady && !accountReader.running)
            accountReader.running = true;
        if (!active) {
            options.close();
            modelPicker.close();
            fileChooser.close();
            filePreview.close();
        }
    }
    Component.onCompleted: {
        componentReady = true;
        if (active)
            accountReader.running = true;
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

    // Assigning composer.text would end its binding to the draft.
    function usePrompt(prompt: string): void {
        AssistantService.draft = prompt;
        composer.cursorPosition = composer.length;
        composer.forceActiveFocus();
    }

    // The toolkit's own clipboard path: no helper process and no argv.
    function copyText(value: string): void {
        clipboardProxy.text = value;
        clipboardProxy.selectAll();
        clipboardProxy.copy();
        clipboardProxy.text = "";
    }

    headerActions: RowLayout {
        spacing: 4
        IconButton {
            objectName: "assistantNew"
            iconName: "plus"
            text: qsTr("New chat")
            hint: qsTr("Fresh chat context · discard conversation and draft")
            enabled: !AssistantService.busy && (AssistantService.messages.count > 0 || !!AssistantService.draft || AssistantService.attachments.length > 0)
            onClicked: {
                AssistantService.newChat();
                composer.forceActiveFocus();
            }
        }
        IconButton {
            objectName: "assistantRelease"
            iconName: "brush-cleaning"
            text: qsTr("Release model memory")
            hint: qsTr("Unload the selected idle model to free memory\nKeeps the chat · the next message reloads the model")
            enabled: AssistantService.online && AssistantService.canRelease
            onClicked: AssistantService.releaseModel()
        }
        IconButton {
            objectName: "assistantOpenApp"
            iconName: "citrus"
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
        spacing: Theme.spacingSmall

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: statusRow.implicitHeight + 12
            visible: !!root.statusText
            radius: 9
            color: Theme.raised
            RowLayout {
                id: statusRow
                anchors.fill: parent
                anchors.leftMargin: Theme.spacingMedium
                anchors.rightMargin: Theme.spacingMedium
                spacing: Theme.spacingSmall
                Rectangle {
                    Layout.preferredWidth: 7
                    Layout.preferredHeight: 7
                    radius: width / 2
                    color: AssistantService.changingServer ? Theme.warning : AssistantService.online ? Theme.success : Theme.muted
                }
                ShellText {
                    id: assistantStatus
                    objectName: "assistantStatus"
                    Layout.fillWidth: true
                    text: root.statusText
                    color: Theme.muted
                    elide: Text.ElideRight
                    font.pixelSize: Theme.smallFontSize
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            visible: !!assistantError.text
            implicitHeight: errorRow.implicitHeight + Theme.spacingMedium * 2
            radius: Theme.controlRadius
            color: Qt.tint(Theme.surface, Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.12))
            border.color: Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.35)
            RowLayout {
                id: errorRow
                anchors.fill: parent
                anchors.margins: Theme.spacingMedium
                spacing: Theme.spacingSmall
                Icon {
                    Layout.preferredWidth: 16
                    Layout.preferredHeight: 16
                    name: "triangle-alert"
                    color: Theme.danger
                }
                ShellText {
                    id: assistantError
                    objectName: "assistantError"
                    Layout.fillWidth: true
                    text: [AssistantService.error, AssistantService.saveError, AssistantService.attachmentError, AssistantService.attachmentHint].filter(Boolean).join("\n")
                    color: Theme.danger
                    wrapMode: Text.Wrap
                    font.pixelSize: Theme.smallFontSize
                }
            }
        }

        Item {
            id: chatArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 50

            ScrollListView {
                id: conversation
                objectName: "assistantConversation"
                anchors.fill: parent
                spacing: Theme.spacingMedium
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
                    required property string reasoningBlocksJson
                    required property string toolActivitiesJson
                    readonly property bool assistant: speaker === "assistant"
                    readonly property var toolActivities: {
                        try {
                            return JSON.parse(toolActivitiesJson || "[]");
                        } catch (_) {
                            return [];
                        }
                    }
                    readonly property var reasoningBlocks: {
                        try {
                            return JSON.parse(reasoningBlocksJson || "[]");
                        } catch (_) {
                            return [];
                        }
                    }
                    readonly property bool isThinking: assistant && state === "streaming" && index === AssistantService.messages.count - 1 && AssistantService.thinking && !AssistantService.cancelling
                    readonly property string activeToolState: toolActivities.find(item => ["pending_approval", "running"].includes(item.state))?.state || ""
                    width: conversation.width
                    implicitHeight: bubble.implicitHeight
                    Card {
                        id: bubble
                        x: message.assistant ? 0 : parent.width - width
                        width: parent.width * (message.assistant ? 1 : 0.92)
                        radius: Theme.controlRadius
                        implicitHeight: messageContent.implicitHeight + Theme.spacingSmall * 2
                        color: message.assistant ? "transparent" : Theme.accentSurface
                        border.color: "transparent"
                        ColumnLayout {
                            id: messageContent
                            anchors.fill: parent
                            anchors.margins: Theme.spacingSmall
                            spacing: Theme.spacingSmall
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.spacingSmall
                                Item {
                                    Layout.preferredWidth: message.assistant ? 14 : 20
                                    Layout.preferredHeight: message.assistant ? 14 : 20
                                    Image {
                                        id: userAvatar
                                        objectName: "assistantAvatar:" + message.index
                                        anchors.fill: parent
                                        source: message.assistant ? "" : root.accountAvatar
                                        sourceSize.width: Math.ceil(width * Screen.devicePixelRatio)
                                        sourceSize.height: Math.ceil(height * Screen.devicePixelRatio)
                                        fillMode: Image.PreserveAspectCrop
                                        asynchronous: true
                                        cache: false
                                        visible: false
                                    }
                                    Rectangle {
                                        id: userAvatarMask
                                        anchors.fill: parent
                                        radius: width / 2
                                        layer.enabled: true
                                        visible: false
                                    }
                                    MultiEffect {
                                        anchors.fill: parent
                                        source: userAvatar
                                        visible: userAvatar.status === Image.Ready
                                        maskEnabled: true
                                        maskSource: userAvatarMask
                                    }
                                    Icon {
                                        objectName: "assistantAvatarFallback:" + message.index
                                        anchors.centerIn: parent
                                        width: 14
                                        height: 14
                                        visible: userAvatar.status !== Image.Ready
                                        name: message.assistant ? "bot" : "user-round"
                                        color: Theme.muted
                                    }
                                }
                                ShellText {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: message.assistant ? message.modelName : qsTr("You")
                                    font.pixelSize: Theme.smallFontSize
                                    font.weight: Font.Medium
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
                                        root.copyText(message.body);
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
                            ColumnLayout {
                                id: content
                                readonly property var parts: {
                                    const entries = [];
                                    let start = 0;
                                    function appendText(from, to) {
                                        Markdown.segments(message.body.slice(from, to)).forEach((part, index) => entries.push(Object.assign({
                                                key: "text:" + from + ":" + index
                                            }, part)));
                                    }
                                    const activities = message.toolActivities.map(activity => ({
                                                key: "tool:" + activity.id,
                                                kind: "tool",
                                                activity,
                                                bodyOffset: activity.bodyOffset || 0,
                                                order: activity.order || 0
                                            }));
                                    for (const block of message.reasoningBlocks) {
                                        activities.push({
                                            key: "thinking:" + block.id,
                                            kind: "thinking",
                                            activity: Object.assign({}, block, {
                                                messageIndex: message.index,
                                                text: message.reasoning.slice(block.start, block.start + block.length),
                                                running: message.isThinking && block.state === "running"
                                            }),
                                            bodyOffset: block.bodyOffset,
                                            order: block.order
                                        });
                                    }
                                    activities.sort((a, b) => a.bodyOffset - b.bodyOffset || a.order - b.order);
                                    for (const entry of activities) {
                                        const end = Math.max(start, Math.min(message.body.length, entry.bodyOffset));
                                        appendText(start, end);
                                        entries.push(entry);
                                        start = end;
                                    }
                                    appendText(start, message.body.length);
                                    return entries;
                                }
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: Theme.spacingMedium
                                visible: parts.length > 0
                                KeyedModel {
                                    id: partsModel
                                    values: content.parts
                                }
                                Repeater {
                                    model: partsModel
                                    delegate: Loader {
                                        id: part
                                        required property int index
                                        required property var modelData
                                        readonly property var entry: modelData
                                        readonly property string segmentText: entry?.text ?? ""
                                        objectName: "assistantSegment:" + message.index + ":" + index
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        Layout.preferredHeight: item?.implicitHeight ?? 0
                                        sourceComponent: entry?.kind === "thinking" ? thinkingBlock : entry?.kind === "tool" ? toolBlock : entry?.kind === "code" ? codeBlock : proseBlock
                                        Binding {
                                            target: part.item
                                            property: ["tool", "thinking"].includes(part.entry?.kind) ? "activityData" : "segmentText"
                                            value: ["tool", "thinking"].includes(part.entry?.kind) ? part.entry.activity : part.segmentText
                                            when: part.status === Loader.Ready
                                        }
                                    }
                                }
                            }
                            RowLayout {
                                objectName: "assistantProgress:" + message.index
                                visible: ["streaming", "stopped", "limited", "error"].includes(message.state) && !message.isThinking
                                spacing: Theme.spacingMedium
                                BusySpinner {
                                    Layout.preferredWidth: 14
                                    Layout.preferredHeight: 14
                                    visible: message.state === "streaming" && message.activeToolState !== "pending_approval"
                                    running: root.active && visible
                                }
                                ShellText {
                                    text: message.state === "error" ? qsTr("Reply failed") : message.state === "stopped" ? qsTr("Stopped") : message.state === "limited" ? qsTr("Output limit reached") : AssistantService.cancelling ? qsTr("Stopping…") : message.activeToolState === "pending_approval" ? qsTr("Waiting for approval…") : message.activeToolState === "running" ? qsTr("Running tools…") : !AssistantService.modelAvailable ? qsTr("Downloading model…") : message.body ? qsTr("Answering…") : AssistantService.thinking ? qsTr("Thinking…") : qsTr("Preparing reply…")
                                    color: Theme.muted
                                    font.pixelSize: Theme.smallFontSize
                                }
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                objectName: "assistantEmpty"
                anchors.centerIn: parent
                width: Math.max(0, parent.width - Theme.paddingLarge * 2)
                visible: AssistantService.messages.count === 0
                spacing: Theme.spacingMedium
                Rectangle {
                    // Decoration only: the text needs a short drawer's space.
                    visible: chatArea.height >= 240
                    Layout.preferredWidth: 60
                    Layout.preferredHeight: 60
                    Layout.alignment: Qt.AlignHCenter
                    radius: 20
                    color: Theme.accentSurface
                    border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.25)
                    Icon {
                        anchors.centerIn: parent
                        width: 32
                        height: 32
                        name: "bot"
                        color: Theme.accent
                    }
                }
                ShellText {
                    Layout.fillWidth: true
                    text: !AssistantService.installed ? qsTr("Your local assistant") : AssistantService.checked && AssistantService.online && !AssistantService.selectedEntry ? qsTr("Choose a model to get started") : qsTr("What’s on your mind?")
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    font.pixelSize: Theme.titleFontSize
                    font.weight: Font.DemiBold
                }
                ShellText {
                    Layout.fillWidth: true
                    text: !AssistantService.installed ? qsTr("Install Lemonade to start a private conversation on this device.") : !AssistantService.selectedEntry ? qsTr("Choose a local model above. Your conversations stay on this device.") : qsTr("Start with a prompt, paste some code, or attach a file for context.")
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: Theme.muted
                }
                RowLayout {
                    objectName: "assistantStarters"
                    Layout.alignment: Qt.AlignHCenter
                    visible: AssistantService.installed && implicitWidth <= parent.width
                    spacing: Theme.spacingSmall
                    Repeater {
                        model: root.promptStarters
                        delegate: Button {
                            id: starter
                            required property var modelData
                            implicitHeight: 34
                            leftPadding: Theme.spacingMedium
                            rightPadding: Theme.spacingMedium
                            text: modelData.label
                            hoverEnabled: true
                            readonly property bool emphasized: hovered || visualFocus
                            objectName: "assistantStarter:" + modelData.label
                            onClicked: root.usePrompt(modelData.prompt)
                            contentItem: ShellText {
                                text: starter.text
                                color: starter.emphasized ? Theme.accent : Theme.text
                                font.pixelSize: Theme.smallFontSize
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle {
                                radius: 17
                                color: starter.emphasized ? Theme.accentSurface : Theme.raised
                                border.color: starter.emphasized ? Theme.accent : Theme.border
                            }
                        }
                    }
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
            implicitHeight: composerLayout.implicitHeight + Theme.spacingSmall * 2
            border.color: composer.activeFocus ? Theme.accent : Theme.border
            border.width: composer.activeFocus ? 2 : 1
            radius: Theme.radius + 3
            ColumnLayout {
                id: composerLayout
                anchors.fill: parent
                anchors.margins: Theme.spacingSmall
                spacing: Theme.spacingSmall
                ScrollView {
                    objectName: "assistantEditor"
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(120, Math.max(34, composer.contentHeight + composer.topPadding + composer.bottomPadding))
                    contentWidth: availableWidth
                    clip: true
                    TextArea {
                        id: composer
                        objectName: "assistantComposer"
                        text: AssistantService.draft
                        onTextChanged: AssistantService.draft = text
                        enabled: AssistantService.installed
                        placeholderText: qsTr("Ask your local assistant…")
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
                        implicitWidth: 36
                        implicitHeight: 36
                        padding: 9
                        iconName: "paperclip"
                        text: qsTr("Attach files")
                        hint: qsTr("Attach images, documents or text/code files\nDrop files here, or paste with Ctrl+V")
                        enabled: !AssistantService.preparing
                        onClicked: fileChooser.open()
                    }
                    ShellButton {
                        id: modelChoice
                        objectName: "assistantModel"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: 30
                        text: AssistantService.selectedEntry?.label || AssistantService.selectedModel || qsTr("Choose a model")
                        iconName: "chevron-down"
                        enabled: AssistantService.installed && !AssistantService.busy
                        Accessible.name: qsTr("Local chat model: %1").arg(text)
                        onClicked: {
                            options.close();
                            modelPicker.visible ? modelPicker.close() : modelPicker.open();
                        }
                        contentItem: RowLayout {
                            spacing: Theme.spacingSmall
                            ShellText {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: modelChoice.text
                                color: modelChoice.enabled ? Theme.text : Theme.muted
                                font.pixelSize: Theme.smallFontSize
                                elide: Text.ElideRight
                            }
                            Icon {
                                Layout.preferredWidth: 12
                                Layout.preferredHeight: 12
                                name: "chevron-down"
                                color: Theme.muted
                            }
                        }
                        PassiveToolTip {
                            target: modelChoice
                            text: modelChoice.text + "\n" + (AssistantService.supportsTools ? qsTr("Agent tools available · commands and writes require approval") : qsTr("Chat model · no agent tools advertised"))
                        }
                    }
                    IconButton {
                        id: optionsButton
                        objectName: "assistantOptions"
                        implicitWidth: 30
                        implicitHeight: 30
                        padding: 7
                        iconName: "sliders-horizontal"
                        text: qsTr("Assistant options")
                        hint: qsTr("Thinking: %1 · Reply: %2\nStyle and model memory").arg(AssistantService.thinkingMode).arg(AssistantService.responseLength)
                        onClicked: {
                            modelPicker.close();
                            options.visible ? options.close() : options.open();
                        }
                    }
                    IconButton {
                        id: sendButton
                        objectName: "assistantSend"
                        implicitWidth: 36
                        implicitHeight: 36
                        padding: 9
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
                            radius: height / 2
                            color: sendButton.enabled && !AssistantService.generating ? (sendButton.down ? Theme.accentSurface : Theme.accent) : sendButton.hovered ? Theme.surface : Theme.raised
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
        y: -height - 6
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
    }
    Process {
        id: accountReader
        command: ["python3", Quickshell.shellPath("drawers/spaces/profile.py")]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const profile = JSON.parse(text);
                    root.accountAvatar = typeof profile.avatar === "string" ? profile.avatar : "";
                } catch (_) {
                    root.accountAvatar = "";
                }
            }
        }
        stderr: StdioCollector {}
    }
    TextEdit {
        id: clipboardProxy
        visible: false
        textFormat: TextEdit.PlainText
    }
    Component {
        id: thinkingBlock
        ColumnLayout {
            id: thinking
            property var activityData: ({})
            property bool expanded: false
            readonly property string identity: activityData.messageIndex + ":" + activityData.id
            spacing: Theme.spacingSmall
            ActivityDisclosure {
                objectName: "assistantReasoning:" + thinking.identity
                Layout.fillWidth: true
                active: root.active
                text: busy ? qsTr("Thinking…") : qsTr("Thinking")
                busy: !!thinking.activityData.running
                expanded: thinking.expanded
                indicatorColor: busy ? Theme.accent : Theme.muted
                hint: expanded ? qsTr("Hide thinking") : qsTr("Show thinking")
                onToggleRequested: thinking.expanded = !thinking.expanded
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(160, thoughts.contentHeight + 12)
                visible: thinking.expanded && !!thinking.activityData.text
                contentWidth: availableWidth
                clip: true
                TextArea {
                    id: thoughts
                    objectName: "assistantReasoningText:" + thinking.identity
                    text: thinking.activityData.text || ""
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
        }
    }
    Component {
        id: toolBlock
        ToolActivity {
            property var activityData: ({})
            active: root.active
            activity: activityData
        }
    }
    Component {
        id: proseBlock
        TextArea {
            property string segmentText: ""
            readonly property bool code: false
            readOnly: true
            selectByMouse: true
            activeFocusOnTab: true
            color: Theme.text
            selectionColor: Theme.accent
            selectedTextColor: Theme.accentText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
            padding: 0
            wrapMode: TextEdit.Wrap
            text: segmentText
            textFormat: TextEdit.MarkdownText
            implicitHeight: contentHeight + topPadding + bottomPadding
            background: null
            Accessible.name: qsTr("Message text")
            onLinkActivated: link => {
                if (/^https?:\/\//i.test(link))
                    Apps.launch(["xdg-open", link]);
            }
        }
    }
    Component {
        id: codeBlock
        Rectangle {
            id: codeBox
            property string segmentText: ""
            readonly property bool code: true
            readonly property alias view: codeView
            implicitHeight: codeText.implicitHeight + (codeView.overflows ? Theme.spacingMedium : 0)
            color: Theme.raised
            radius: Theme.controlRadius
            // Long lines scroll sideways; vertical scrolling stays with the chat.
            Flickable {
                id: codeView
                readonly property bool overflows: contentWidth > width + 1
                anchors.fill: parent
                contentWidth: Math.max(width, codeText.contentWidth + codeText.leftPadding + codeText.rightPadding)
                contentHeight: height
                flickableDirection: Flickable.HorizontalFlick
                boundsBehavior: Flickable.StopAtBounds
                interactive: overflows
                clip: true
                ScrollBar.horizontal: ScrollBar {
                    policy: codeView.overflows ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                }
                WheelScroll {
                    view: codeView
                    orientation: Qt.Horizontal
                }
                TextArea {
                    id: codeText
                    objectName: "assistantCode"
                    width: codeView.contentWidth
                    height: implicitHeight
                    readOnly: true
                    selectByMouse: true
                    activeFocusOnTab: true
                    color: Theme.text
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.accentText
                    font.family: Theme.monospaceFamily
                    font.pixelSize: Theme.smallFontSize
                    padding: Theme.spacingMedium
                    rightPadding: copyCode.width + Theme.spacingMedium
                    wrapMode: TextEdit.NoWrap
                    text: codeBox.segmentText
                    textFormat: TextEdit.PlainText
                    implicitHeight: contentHeight + topPadding + bottomPadding
                    background: null
                    Accessible.name: qsTr("Code")
                }
            }
            IconButton {
                id: copyCode
                objectName: "assistantCodeCopy"
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.margins: 3
                implicitWidth: 26
                implicitHeight: 26
                padding: 5
                iconName: codeCopied.running ? "check" : "copy"
                text: codeCopied.running ? qsTr("Copied") : qsTr("Copy code")
                onClicked: {
                    root.copyText(codeBox.segmentText);
                    codeCopied.restart();
                }
                Timer {
                    id: codeCopied
                    interval: 1500
                }
            }
        }
    }
    ModelPicker {
        id: modelPicker
        objectName: "assistantModelPopup"
        button: modelChoice
        y: -height - 6
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
