pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

ColumnLayout {
    id: root
    objectName: "assistantToolActivity:" + activity.id
    required property var activity
    property bool showDetails: false
    property bool active: true
    property var output: null
    property bool approvalCollapsed: false
    readonly property bool detailsExpanded: showDetails || (approvalPending && !approvalCollapsed)
    readonly property var args: activity.arguments || ({})
    readonly property var result: activity.result || ({})
    readonly property bool approvalPending: activity.state === "pending_approval"
    readonly property string title: {
        switch (activity.name) {
        case "search_spaces":
            return qsTr("Search Spaces · %1").arg(args.kind || "");
        case "space_filters":
            return qsTr("Inspect Space filters · %1").arg(args.kind || "");
        case "present_space_results":
            return result.title || args.title || qsTr("Recommendations");
        case "web_search":
            return qsTr("Search web");
        case "read_web_page":
            return qsTr("Read web page");
        case "search_lyrics":
            return qsTr("Identify song from lyrics");
        case "get_song_lyrics":
            return qsTr("Read song lyrics");
        case "inspect_system":
            return qsTr("Inspect system · %1").arg(String(args.query || "state").replace(/_/g, " "));
        case "read_file":
            return qsTr("Read file");
        case "list_directory":
            return qsTr("List directory");
        case "search_files":
            return args.mode === "files" ? qsTr("Find files") : qsTr("Search files");
        case "run_command":
            return qsTr("Run command");
        case "write_file":
            return qsTr("Write file");
        default:
            return activity.name || qsTr("Tool call");
        }
    }
    readonly property string target: {
        if (activity.name === "search_spaces") {
            const parts = args.query ? [String(args.query)] : [];
            parts.push(...Object.keys(args.filters || {}).map(key => key.replace(/_/g, " ") + ": " + args.filters[key]));
            return parts.join(" · ");
        }
        if (activity.name === "run_command")
            return String(args.command || "");
        if (activity.name === "web_search")
            return String(args.query || "");
        if (activity.name === "read_web_page")
            return String(result.title || args.url || "");
        if (activity.name === "search_lyrics")
            return String(args.fragment || "");
        if (activity.name === "get_song_lyrics")
            return [result.title, result.artist].filter(Boolean).join(" · ");
        if (activity.name === "search_files")
            return String(args.path || "") + " · " + String(args.pattern || "");
        return String(args.path || "");
    }
    readonly property string statusLabel: {
        if (approvalPending)
            return qsTr("Pending approval");
        if (activity.state === "running")
            return qsTr("Running");
        if (activity.state === "completed")
            return qsTr("Completed");
        if (activity.state === "failed")
            return qsTr("Failed");
        if (activity.state === "rejected")
            return qsTr("Rejected");
        if (activity.state === "cancelled")
            return qsTr("Cancelled");
        return activity.state || qsTr("Pending");
    }
    readonly property color statusColor: approvalPending ? Theme.warning : activity.state === "completed" ? Theme.success : ["failed", "rejected"].includes(activity.state) ? Theme.danger : activity.state === "cancelled" ? Theme.muted : Theme.accent
    readonly property string argumentsText: {
        if (activity.name === "run_command")
            return String(args.command || "");
        if (activity.name === "write_file")
            return String(args.path || "") + "\n\n" + String(args.content || "");
        return JSON.stringify(args, null, 2);
    }
    readonly property string resultText: {
        const parts = [];
        if (result.stdout)
            parts.push("stdout:\n" + result.stdout);
        if (result.stderr)
            parts.push("stderr:\n" + result.stderr);
        if (result.error)
            parts.push("Error: " + result.error);
        if (result.exit_code !== undefined)
            parts.push("Exit code: " + result.exit_code);
        if (result.duration_ms !== undefined)
            parts.push("Duration: " + result.duration_ms + " ms");
        if (result.timed_out)
            parts.push("Command timed out.");
        if (result.truncated)
            parts.push("Output was truncated.");
        if (result.path)
            parts.push("Path: " + result.path);
        if (result.written_bytes !== undefined)
            parts.push("Written bytes: " + result.written_bytes);
        if (result.content)
            parts.push(result.content);
        if (result.provider)
            parts.push(qsTr("Source: %1").arg(result.provider) + (result.saved ? qsTr(" · Saved lyrics") : ""));
        if (result.has_more)
            parts.push(qsTr("More text available at offset %1").arg(result.next_offset));
        if (result.entries)
            parts.push(result.entries.map(item => item.url ? item.title + "\n" + item.url + "\n" + (item.snippet || "") : item.type + "  " + item.name).join("\n\n"));
        if (result.warning)
            parts.push(result.warning);
        if (["search_spaces", "search_lyrics"].includes(activity.name) && result.items?.length)
            parts.push(result.items.map(item => item.title + "\n" + JSON.stringify(item.metadata || {})).join("\n\n"));
        if (activity.name === "space_filters")
            parts.push(JSON.stringify(result, null, 2));
        return parts.join("\n\n");
    }
    readonly property string headerText: title + (target ? " · " + target : "") + ((activity.batch_size || 1) > 1 ? " · " + activity.batch_index + "/" + activity.batch_size : "") + (!["running", "completed"].includes(activity.state) ? " · " + statusLabel : "")
    spacing: Theme.spacingSmall
    ActivityDisclosure {
        objectName: "assistantToolDetails:" + root.activity.id
        Layout.fillWidth: true
        active: root.active
        text: root.headerText
        hint: root.statusLabel + " · " + (root.detailsExpanded ? qsTr("Hide details") : qsTr("Show details"))
        indicatorColor: root.statusColor
        busy: root.activity.state === "running"
        expanded: root.detailsExpanded
        onToggleRequested: {
            const expand = !root.detailsExpanded;
            root.showDetails = expand;
            if (root.approvalPending)
                root.approvalCollapsed = !expand;
        }
    }
    Repeater {
        model: root.activity.name === "present_space_results" || (["search_spaces", "search_lyrics"].includes(root.activity.name) && root.result.display !== false) ? root.result.items || [] : []
        SpaceResultCard {
            required property var modelData
            Layout.fillWidth: true
            result: modelData
            output: root.output
        }
    }
    Repeater {
        model: ["web_search", "search_lyrics"].includes(root.activity.name) ? root.result.entries || [] : root.activity.name === "read_web_page" && root.result.url ? [
            {
                title: root.result.title,
                url: root.result.url
            }
        ] : []
        ShellButton {
            required property var modelData
            objectName: "assistantWebSource:" + root.activity.id + ":" + index
            required property int index
            Layout.fillWidth: true
            text: modelData.title || modelData.url || ""
            iconName: "globe"
            enabled: /^https?:\/\//.test(modelData.url || "")
            ToolTip.visible: hovered
            ToolTip.text: modelData.url || ""
            onClicked: Apps.openUrl(modelData.url, "assistant")
        }
    }
    ShellText {
        Layout.fillWidth: true
        visible: root.activity.name === "get_song_lyrics" && root.activity.state === "completed"
        text: root.result.available ? qsTr("Lyrics · %1").arg(root.result.provider || qsTr("Library")) + (root.result.saved ? qsTr(" · Saved") : "") : qsTr("No lyrics available")
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap
    }
    ShellText {
        Layout.fillWidth: true
        visible: ["search_spaces", "space_filters", "web_search", "search_lyrics"].includes(root.activity.name) && !!root.result.warning
        text: root.result.warning || ""
        color: Theme.warning
        font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: root.detailsExpanded
        spacing: Theme.spacingSmall
        ShellText {
            Layout.fillWidth: true
            visible: !!root.activity.working_directory
            text: qsTr("In %1 · %2 s limit").arg(root.activity.working_directory || "").arg(root.activity.timeout_seconds || 30)
            font.pixelSize: Theme.smallFontSize
            color: Theme.muted
            wrapMode: Text.Wrap
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(180, argumentsText.implicitHeight + 8)
            visible: !!root.argumentsText
            color: Theme.background
            radius: Theme.controlRadius
            border.color: Theme.border
            Flickable {
                id: argumentsView
                anchors.fill: parent
                anchors.margins: 4
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.AutoFlickIfNeeded
                contentWidth: Math.max(width, argumentsText.contentWidth + argumentsText.leftPadding + argumentsText.rightPadding)
                contentHeight: argumentsText.implicitHeight
                ScrollBar.horizontal: ScrollBar {}
                ScrollBar.vertical: ScrollBar {}
                WheelScroll {
                    view: argumentsView
                }
                WheelScroll {
                    view: argumentsView
                    orientation: Qt.Horizontal
                }
                TextArea {
                    id: argumentsText
                    objectName: "assistantToolInput:" + root.activity.id
                    text: root.argumentsText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.NoWrap
                    textFormat: TextEdit.PlainText
                    color: Theme.text
                    font.family: Theme.monospaceFamily
                    font.pixelSize: Theme.smallFontSize
                    background: null
                    width: argumentsView.contentWidth
                    padding: 4
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(180, resultText.implicitHeight + 8)
            visible: !root.approvalPending && !!root.resultText
            color: Theme.background
            radius: Theme.controlRadius
            border.color: Theme.border
            Flickable {
                id: resultView
                anchors.fill: parent
                anchors.margins: 4
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.AutoFlickIfNeeded
                contentWidth: Math.max(width, resultText.contentWidth + resultText.leftPadding + resultText.rightPadding)
                contentHeight: resultText.implicitHeight
                ScrollBar.horizontal: ScrollBar {}
                ScrollBar.vertical: ScrollBar {}
                WheelScroll {
                    view: resultView
                }
                WheelScroll {
                    view: resultView
                    orientation: Qt.Horizontal
                }
                TextArea {
                    id: resultText
                    objectName: "assistantToolOutput:" + root.activity.id
                    text: root.resultText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.NoWrap
                    textFormat: TextEdit.PlainText
                    color: Theme.muted
                    font.family: Theme.monospaceFamily
                    font.pixelSize: Theme.smallFontSize
                    background: null
                    width: resultView.contentWidth
                    padding: 4
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            visible: root.approvalPending
            spacing: Theme.spacingSmall
            ShellText {
                Layout.fillWidth: true
                text: root.activity.name === "write_file" ? qsTr("This replaces the entire file. Review all content before approving.") : qsTr("This command will run only after you approve it.")
                color: Theme.warning
                font.pixelSize: Theme.smallFontSize
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: Theme.spacingSmall
                ShellButton {
                    objectName: "assistantToolReject:" + root.activity.id
                    text: qsTr("Reject")
                    enabled: !root.activity.decisionSent && !AssistantService.cancelling
                    iconName: "x"
                    onClicked: AssistantService.decideTool(root.activity.id, false)
                }
                ShellButton {
                    objectName: "assistantToolApprove:" + root.activity.id
                    text: qsTr("Approve")
                    enabled: !root.activity.decisionSent && !AssistantService.cancelling
                    iconName: "check"
                    onClicked: AssistantService.decideTool(root.activity.id, true)
                }
            }
        }
    }
}
