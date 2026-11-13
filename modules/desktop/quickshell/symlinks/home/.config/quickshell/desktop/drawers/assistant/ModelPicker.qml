pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

Popup {
    id: root
    required property Item button
    property bool active: false
    property real maximumWidth: 432
    property int deleteHoldDuration: 1300
    property int searchRefresh: 0
    readonly property string query: search.text.trim()
    readonly property bool searchOnline: visible && AssistantService.online && query.length >= 3 && query.length <= 256
    readonly property var rows: {
        const query = search.text.trim().toLowerCase();
        return AssistantService.models.filter(row => (!AssistantService.needsVision || row.labels.includes("vision")) && (row.id + " " + (row.target || "") + " " + row.labels.join(" ")).toLowerCase().includes(query));
    }
    parent: button
    popupType: Popup.Item
    y: button.height + 6
    x: Math.max(-button.x, button.width - width)
    width: Math.min(maximumWidth, 432, Math.max(0, (Overlay.overlay?.width ?? 448) - 32))
    height: Math.min(520, Math.max(0, (Overlay.overlay?.height ?? 640) - 32))
    padding: 12
    margins: 8
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    onActiveChanged: if (!active)
        close()
    onOpened: {
        AssistantService.connect();
        search.clear();
        search.forceActiveFocus(Qt.PopupFocusReason);
        Qt.callLater(revealSelected);
    }
    Connections {
        target: AssistantService
        function onModelsChanged(): void {
            if (root.visible)
                Qt.callLater(root.revealSelected);
        }
        function onModelInstalled(id: string): void {
            if (root.visible)
                search.clear();
        }
    }
    function revealSelected(): void {
        const selected = root.rows.findIndex(row => row.id === AssistantService.selectedModel);
        if (visible && selected >= 0)
            list.positionViewAtIndex(selected, ListView.Contain);
    }
    onClosed: if (active)
        button.forceActiveFocus()
    function sizeText(size): string {
        return size >= 1 ? qsTr("%1 GB").arg(Number(size).toFixed(1)) : size > 0 ? qsTr("%1 MB").arg(Math.round(size * 1000)) : "";
    }
    function capabilities(entry): var {
        return [entry.labels.includes("coding") ? qsTr("Code") : "", entry.labels.includes("reasoning") ? qsTr("Reasoning") : "", entry.labels.includes("vision") ? qsTr("Vision") : "", entry.labels.includes("tool-calling") ? qsTr("Tool calling") : ""].filter(Boolean);
    }
    function progress(job): real {
        if (!job)
            return -1;
        const total = job.total_download_size || job.bytes_total || 0;
        const done = job.cumulative_bytes_downloaded || job.overall_bytes_downloaded || job.bytes_downloaded || 0;
        return total > 0 ? Math.max(0, Math.min(1, done / total)) : -1;
    }
    background: Surface {
        color: Theme.background
        radius: Theme.controlRadius
    }
    contentItem: ColumnLayout {
        spacing: Theme.spacingMedium
        RowLayout {
            Layout.fillWidth: true
            InputField {
                id: search
                objectName: "assistantModelSearch"
                Layout.fillWidth: true
                placeholderText: AssistantService.needsVision ? qsTr("Find a vision model") : qsTr("Find a model")
                Accessible.name: placeholderText
            }
            IconButton {
                objectName: "assistantModelsRefresh"
                iconName: "refresh-cw"
                text: qsTr("Refresh models")
                enabled: !AssistantService.checking
                onClicked: {
                    AssistantService.catalogueGeneration = null;
                    AssistantService.refresh();
                    root.searchRefresh++;
                }
            }
        }
        ScrollListView {
            id: list
            objectName: "assistantModelResults"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.spacingMedium
            model: KeyedModel {
                keyField: "id"
                values: root.visible ? root.rows : []
            }
            ScrollBar.vertical: ScrollBar {}
            footer: Column {
                width: list.width
                spacing: Theme.spacingMedium
                ShellText {
                    width: parent.width
                    visible: root.rows.length === 0
                    text: AssistantService.checking ? qsTr("Loading models…") : root.query ? qsTr("No matching local models") : qsTr("No models available")
                    color: Theme.muted
                    wrapMode: Text.Wrap
                }
                Repeater {
                    model: ["huggingface", "modelscope"]
                    delegate: RegistryModels {
                        required property string modelData
                        width: list.width
                        source: modelData
                        query: root.query
                        active: root.searchOnline
                        refreshToken: root.searchRefresh
                    }
                }
            }
            delegate: Column {
                id: row
                required property int index
                required property var modelData
                readonly property string targetModel: modelData.target || modelData.id
                readonly property var job: AssistantService.downloads.find(job => job.model_name === targetModel && job.status !== "completed") ?? null
                readonly property bool selected: AssistantService.selectedModel === modelData.id
                readonly property var loadedModel: AssistantService.loaded.find(item => item.id === targetModel) ?? null
                readonly property bool loaded: !!loadedModel
                readonly property real fraction: root.progress(job)
                // Lemonade keeps a stopped job listed; pulling again restarts it.
                readonly property bool stalled: !!job && !job.running && ["paused", "error", "cancelled"].includes(job.status)
                width: list.width
                spacing: Theme.spacingMedium
                Rectangle {
                    objectName: visible ? "assistantModelSeparator" : ""
                    width: parent.width
                    height: visible ? 1 : 0
                    visible: row.index > 0 && !!root.rows[row.index - 1]?.alias && !row.modelData.alias && root.rows[row.index - 1]?.downloaded === row.modelData.downloaded
                    color: Theme.border
                }
                Button {
                    id: modelButton
                    objectName: "assistantModelRow:" + row.modelData.id
                    width: parent.width
                    implicitHeight: contentItem.implicitHeight + topPadding + bottomPadding
                    padding: Theme.spacingMedium
                    hoverEnabled: true
                    enabled: !AssistantService.busy
                    text: qsTr("Use %1").arg(row.modelData.label)
                    Accessible.name: text
                    onClicked: {
                        AssistantService.chooseModel(row.modelData.id);
                        root.close();
                    }
                    background: ButtonBackground {
                        idleColor: Theme.surface
                        idleBorderColor: row.selected ? Theme.accent : Theme.border
                        highlighted: modelButton.hovered || modelButton.visualFocus
                        pressed: modelButton.down
                    }
                    PassiveToolTip {
                        objectName: "assistantModelToolTip:" + row.modelData.id
                        target: modelButton
                        maximumLineCount: 20
                        text: action.hovered || action.visualFocus || remove.hovered || remove.visualFocus ? "" : [row.modelData.id, row.modelData.alias ? qsTr("Alias for %1").arg(row.targetModel) : "", row.modelData.downloaded ? qsTr("Downloaded") : qsTr("Downloads on first message"), row.loaded ? qsTr("Loaded in Lemonade") : "", row.loadedModel?.busy ? qsTr("In use · deletion unavailable") : "", row.loadedModel?.pinned ? qsTr("Pinned in Lemonade · deletion unavailable") : "", root.sizeText(row.modelData.size), ...root.capabilities(row.modelData), row.modelData.suggested ? qsTr("Suggested by Lemonade") : "", row.job?.error || ""].filter(Boolean).join("\n")
                    }
                    contentItem: ColumnLayout {
                        spacing: Theme.spacingSmall
                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: Theme.spacingSmall
                                ShellText {
                                    Layout.fillWidth: true
                                    text: row.modelData.label
                                    elide: Text.ElideRight
                                    font.weight: row.selected ? Font.Medium : Font.Normal
                                }
                                ShellText {
                                    Layout.fillWidth: true
                                    visible: !!row.modelData.alias
                                    text: row.targetModel
                                    font.pixelSize: Theme.smallFontSize
                                    color: Theme.muted
                                    elide: Text.ElideMiddle
                                }
                                ShellText {
                                    Layout.fillWidth: true
                                    text: [root.sizeText(row.modelData.size), row.loaded ? qsTr("Loaded") : row.job?.running ? (row.fraction >= 0 ? qsTr("Downloading · %1%").arg(Math.floor(row.fraction * 100)) : qsTr("Downloading…")) : row.job?.status === "paused" ? qsTr("Paused") : row.job?.error ? qsTr("Download failed") : row.modelData.downloaded ? qsTr("Downloaded") : "", ...root.capabilities(row.modelData)].filter(Boolean).join(" · ")
                                    font.pixelSize: Theme.smallFontSize
                                    color: row.job?.error ? Theme.danger : Theme.muted
                                    elide: Text.ElideRight
                                }
                            }
                            Icon {
                                objectName: "assistantModelIndicator:" + row.modelData.id
                                name: "download"
                                color: row.selected ? Theme.accent : Theme.muted
                                visible: !action.visible && !remove.visible
                                Layout.preferredWidth: Theme.controlHeight
                                Layout.preferredHeight: Theme.iconSize
                            }
                            IconButton {
                                id: action
                                objectName: "assistantModelAction:" + row.modelData.id
                                visible: !row.modelData.downloaded && (!!row.job?.running || row.stalled)
                                iconName: row.job?.running ? "pause" : "download"
                                text: row.job?.running ? qsTr("Pause download") : row.job?.status === "paused" ? qsTr("Resume download") : qsTr("Retry download")
                                enabled: !AssistantService.busy && AssistantService.online
                                onClicked: {
                                    if (row.job?.running)
                                        AssistantService.pauseDownload(row.modelData.id);
                                    else
                                        AssistantService.downloadModel(row.modelData.id);
                                }
                            }
                            HoldButton {
                                id: remove
                                objectName: "assistantModelDelete:" + row.modelData.id
                                visible: row.modelData.downloaded
                                text: qsTr("Hold to delete %1 from disk").arg(row.targetModel)
                                hint: [row.modelData.alias ? qsTr("Removes the underlying model used by this alias.") : "", row.targetModel.startsWith("user.") || row.modelData.labels.includes("custom") ? qsTr("Also removes its custom model registration in Lemonade.") : ""].filter(Boolean).join("\n")
                                Accessible.name: text
                                implicitWidth: Theme.controlHeight
                                implicitHeight: Theme.controlHeight
                                horizontalPadding: 8
                                verticalPadding: 8
                                idleColor: "transparent"
                                holdDuration: root.deleteHoldDuration
                                enabled: AssistantService.canDeleteModel(row.modelData.id)
                                armed: root.visible
                                contentItem: Icon {
                                    name: "trash"
                                    color: remove.hovered || remove.visualFocus ? Theme.accent : Theme.muted
                                }
                                onConfirmed: AssistantService.deleteModel(row.modelData.id)
                            }
                        }
                        ProgressBar {
                            id: progressBar
                            Layout.fillWidth: true
                            visible: !!row.job && (row.job.running || row.job.status === "paused")
                            from: 0
                            to: 1
                            value: Math.max(0, row.fraction)
                            indeterminate: row.fraction < 0 && !!row.job?.running
                            implicitHeight: 4
                            background: Rectangle {
                                color: Theme.raised
                                radius: 2
                            }
                            contentItem: Item {
                                Rectangle {
                                    width: progressBar.indeterminate ? parent.width / 3 : progressBar.visualPosition * parent.width
                                    height: 4
                                    radius: 2
                                    color: Theme.accent
                                }
                            }
                        }
                    }
                }
            }
        }
        ShellText {
            objectName: "assistantModelError"
            Layout.fillWidth: true
            visible: !!text
            text: AssistantService.error
            color: Theme.danger
            font.pixelSize: Theme.smallFontSize
            wrapMode: Text.Wrap
        }
    }
}
